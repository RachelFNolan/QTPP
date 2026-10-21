from __future__ import annotations

import argparse
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from .workspace import Workspace, WorkspaceError

WEB_ROOT = Path(__file__).resolve().parent / "web"
MAX_REQUEST_BYTES = 32 * 1024 * 1024


class WorkspaceHandler(BaseHTTPRequestHandler):
    server_version = "QTPPWorkspace/1.0"

    @property
    def workspace(self) -> Workspace:
        return cast(WorkspaceServer, self.server).workspace

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route == "/api/options":
            self._json_response(self.workspace.options())
        elif route == "/api/templates":
            self._json_response({"templates": self.workspace.templates()})
        else:
            self._static_response(route)

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if not route.startswith("/api/"):
            self._json_response({"error": "Not found."}, status=404)
            return
        if not self._same_origin_or_no_origin():
            self._json_response({"error": "Cross-origin requests are not accepted."}, status=403)
            return
        try:
            payload = self._read_json()
            if route == "/api/import":
                result = self.workspace.import_csv(
                    payload.get("csv", ""), payload.get("filename", "question-pool.csv")
                )
            elif route == "/api/import-json":
                result = self.workspace.import_json(
                    payload.get("json", ""), payload.get("filename", "question-pool.json")
                )
            elif route == "/api/demo":
                result = self.workspace.import_demo()
            elif route == "/api/feasibility":
                result = self.workspace.feasibility(payload.get("template"), payload.get("packet_count"))
            elif route == "/api/suggest-template":
                result = self.workspace.suggest_template(payload)
            elif route == "/api/generate":
                result = self.workspace.generate(payload)
            elif route == "/api/review":
                result = self.workspace.review(payload.get("packets"))
            elif route == "/api/audit":
                result = self.workspace.audit(payload.get("request", ""))
            elif route == "/api/select-run":
                result = self.workspace.select_run(payload.get("run_index"))
            elif route == "/api/export":
                result = self.workspace.export()
            else:
                self._json_response({"error": "Not found."}, status=404)
                return
        except WorkspaceError as error:
            self._json_response({"error": str(error)}, status=422)
            return
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._json_response({"error": f"Invalid JSON request: {error}"}, status=400)
            return
        self._json_response(result)

    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise WorkspaceError("Content-Length must be an integer.") from error
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise WorkspaceError(f"Request body exceeds {MAX_REQUEST_BYTES} bytes.")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise WorkspaceError("Request body must be a JSON object.")
        return value

    def _same_origin_or_no_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }

    def _static_response(self, route: str) -> None:
        if route == "/README.md":
            target = WEB_ROOT.parent.parent / "README.md"
        else:
            relative = "index.html" if route == "/" else route.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if not target.is_relative_to(WEB_ROOT.resolve()):
                self._json_response({"error": "Not found."}, status=404)
                return
        if not target.is_file():
            self._json_response({"error": "Not found."}, status=404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; style-src 'self'; "
            "script-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: object) -> None:
        logging.info("%s - %s", self.address_string(), format % args)


class WorkspaceServer(ThreadingHTTPServer):
    def __init__(self, port: int, workspace: Workspace | None = None) -> None:
        super().__init__(("127.0.0.1", port), WorkspaceHandler)
        self.workspace = workspace or Workspace()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local QTPP packet-building workspace.")
    parser.add_argument("--port", type=int, default=8765, help="Local HTTP port (default: 8765)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    server = WorkspaceServer(args.port)
    print(f"QTPP workspace is available at http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping QTPP workspace.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
