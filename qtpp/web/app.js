"use strict";

const state = {
  templates: [],
  options: null,
  pool: null,
  payload: null,
  layouts: null,
  template: null,
  dirty: false,
  demo: false,
  demoStage: 0,
  selectedFile: null,
};

const titles = {
  import: "Import a question pool",
  configure: "Configure packet rules",
  compare: "Compare build approaches",
  review: "Review and arrange packets",
  audit: "Investigate packet composition",
  export: "Export packet JSON",
};
const demoStages = [
  ["configure", "Choose a ready-to-use template and packet count."],
  ["compare", "Select a solver and similarity scorer, then run one or more builds."],
  ["review", "Inspect a result, move or reorder questions, and recalculate validation."],
  ["audit", "Ask a composition question and review the evidence and likely conflicts."],
  ["export", "Download the reviewed packet JSON files."],
];

const byId = (id) => document.getElementById(id);

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const contentType = response.headers.get("content-type") || "";
  const result = contentType.includes("application/json")
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function setNotice(message, kind = "") {
  const notice = byId("notice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.hidden = !message;
  if (message) {
    window.clearTimeout(setNotice.timer);
    setNotice.timer = window.setTimeout(() => { notice.hidden = true; }, 7000);
  }
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = label || "Working…";
  } else {
    button.disabled = false;
    if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
  }
}

function showView(view) {
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  byId("page-title").textContent = titles[view] || "QTPP Packet Workshop";
  if (view === "review") renderReview();
}

function poolLoaded(pool) {
  state.pool = pool;
  byId("pool-pill").textContent = `${pool.tossup_count} tossups · ${pool.bonus_count} bonuses`;
  byId("pool-pill").className = "pill good";
  const summary = byId("pool-summary");
  summary.hidden = false;
  summary.innerHTML = `
    <h3>${escapeHtml(pool.metadata.name || "Question pool")}</h3>
    <div class="pool-stats">
      <span class="stat-chip">${pool.tossup_count.toLocaleString()} tossups</span>
      <span class="stat-chip">${pool.bonus_count.toLocaleString()} bonuses</span>
      <span class="stat-chip">${escapeHtml(pool.metadata.year ?? "Year unknown")}</span>
    </div>
    <div class="category-wrap">${Object.entries(pool.categories).map(([category, subs]) =>
      `<span class="category-chip">${escapeHtml(category)} · ${subs.length} subcategories</span>`
    ).join("")}</div>`;
  const categories = Object.keys(pool.categories);
  byId("category-options").innerHTML = categories.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  byId("subcategory-options").innerHTML = [...new Set(Object.values(pool.categories).flat())]
    .sort().map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  byId("config-pool-hint").innerHTML =
    `<strong>${categories.length} categories available</strong><br>${categories.slice(0, 8).map(escapeHtml).join(" · ")}${categories.length > 8 ? " · …" : ""}`;
}

function quotaRow(quota = {}) {
  const selector = quota.selector || {};
  return `<div class="quota-row">
    <select class="quota-type" aria-label="Question type">
      <option value="tossup" ${selector.question_type === "tossup" ? "selected" : ""}>Tossup</option>
      <option value="bonus" ${selector.question_type === "bonus" ? "selected" : ""}>Bonus</option>
    </select>
    <input class="quota-category" list="category-options" value="${escapeHtml(selector.category || "")}" placeholder="Category" aria-label="Category">
    <input class="quota-subcategory" list="subcategory-options" value="${escapeHtml(selector.subcategory || "")}" placeholder="Subcategory (optional)" aria-label="Subcategory">
    <input class="quota-min" type="number" min="0" value="${Number(quota.minimum || 0)}" aria-label="Minimum">
    <input class="quota-max" type="number" min="0" value="${quota.maximum == null ? "" : Number(quota.maximum)}" placeholder="Max" aria-label="Maximum">
    <button type="button" class="remove-row" aria-label="Remove quota">×</button>
  </div>`;
}

function currentTemplateFromForm() {
  const quotas = [...document.querySelectorAll(".quota-row")].map((row, index) => {
    const category = row.querySelector(".quota-category").value.trim();
    if (!category) throw new Error(`Quota ${index + 1} needs a category.`);
    const maximumValue = row.querySelector(".quota-max").value;
    return {
      selector: {
        question_type: row.querySelector(".quota-type").value,
        category,
        subcategory: row.querySelector(".quota-subcategory").value.trim() || null,
      },
      minimum: Number(row.querySelector(".quota-min").value || 0),
      maximum: maximumValue === "" ? null : Number(maximumValue),
    };
  });
  let patterns;
  try {
    patterns = JSON.parse(byId("patterns-json").value || "[]");
  } catch (error) {
    throw new Error(`Allowed-pattern JSON is invalid: ${error.message}`);
  }
  if (!Array.isArray(patterns)) throw new Error("Allowed-pattern rules must be a JSON array.");
  const leftoverBounds = ["tossup", "bonus"].map((type) => ({
    question_type: type,
    minimum: 0,
    maximum: byId(type === "tossup" ? "leftover-tu" : "leftover-bonus").value === ""
      ? null
      : Number(byId(type === "tossup" ? "leftover-tu" : "leftover-bonus").value),
  }));
  state.dirty = false;
  return {
    schema_version: 1,
    name: byId("template-name").value.trim() || "Custom template",
    tossup_capacity: Number(byId("tossup-capacity").value),
    bonus_capacity: Number(byId("bonus-capacity").value),
    quotas,
    allowed_patterns: patterns,
    leftover_bounds: leftoverBounds,
  };
}

function loadTemplateForm(template) {
  state.template = structuredClone(template);
  byId("template-name").value = template.name || "";
  byId("tossup-capacity").value = template.tossup_capacity ?? 20;
  byId("bonus-capacity").value = template.bonus_capacity ?? 20;
  byId("quota-list").innerHTML = (template.quotas || []).map(quotaRow).join("");
  byId("patterns-json").value = JSON.stringify(template.allowed_patterns || [], null, 2);
  const leftovers = template.leftover_bounds || [];
  const tu = leftovers.find((item) => item.question_type === "tossup");
  const bonus = leftovers.find((item) => item.question_type === "bonus");
  byId("leftover-tu").value = tu?.maximum ?? "";
  byId("leftover-bonus").value = bonus?.maximum ?? "";
}

function renderOptions() {
  const solverHost = byId("solver-options");
  solverHost.innerHTML = state.options.solvers.map((item, index) => `
    <label class="choice">
      <input type="checkbox" name="solver" value="${escapeHtml(item.id)}" ${index === 0 ? "checked" : ""} ${item.available ? "" : "disabled"}>
      <span><strong>${escapeHtml(item.label)}${item.available ? "" : " · unavailable"}</strong>
      <small>${item.available ? (item.id === "cpsat" ? "Exact hard constraints; optional OR-Tools dependency." : "Fast, repeatable local search; core dependency-free solver.") : `Install with ${escapeHtml(item.install || "the optional dependency set")}.`}</small></span>
    </label>`).join("");
  byId("similarity-options").innerHTML = state.options.similarities.map((item, index) => `
    <label class="choice">
      <input type="checkbox" name="similarity" value="${escapeHtml(item.id)}" ${index === 0 ? "checked" : ""}>
      <span><strong>${escapeHtml(item.label)}</strong><small>Same hard rules; compare the soft-score result.</small></span>
    </label>`).join("");
}

function updateRunState(payload) {
  state.payload = payload;
  state.layouts = payload.draft.packets.map((packet) => ({
    tossups: [...packet.tossups],
    bonuses: [...packet.bonuses],
  }));
  renderComparison();
  renderReview();
}

function renderComparison() {
  const host = byId("comparison-results");
  if (!state.payload) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = state.payload.runs.map((run) => {
    const selected = run.index === state.payload.selected_run;
    const score = run.index === state.payload.selected_run
      ? state.payload.draft.report.score
      : run.score;
    return `<article class="result-card ${selected ? "selected" : ""}">
      <div class="result-head"><strong>${escapeHtml(run.solver)} · ${escapeHtml(run.similarity)}</strong>
        ${selected ? '<span class="pill good">Reviewing</span>' : ""}</div>
      <div class="score">${Number(score.total).toFixed(2)} <small>penalty · lower is better</small></div>
      <div class="score-detail">
        <span>Adjacency<br>${Number(score.adjacent_category).toFixed(2)}</span>
        <span>Same packet<br>${Number(score.same_packet).toFixed(2)}</span>
        <span>Nearby<br>${Number(score.nearby).toFixed(2)}</span>
      </div>
      <p class="result-meta">${Number(run.seconds).toFixed(2)}s · seed ${run.seed} · ${run.leftover_count} leftover</p>
      <button class="button secondary small" data-select-run="${run.index}" ${selected ? "disabled" : ""}>${selected ? "Selected for review" : "Review this result"}</button>
    </article>`;
  }).join("");
}

function reviewMessage() {
  if (!state.payload) return "";
  const report = state.payload.draft.report;
  if (report.hard_errors.length) {
    return `<div class="review-banner error"><strong>Hard-rule violations: ${report.hard_errors.length}</strong><ul>${report.hard_errors.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}</ul></div>`;
  }
  if (report.leftover_ids.length) {
    return `<div class="review-banner warn"><strong>Valid draft with ${report.leftover_ids.length} unassigned pool questions.</strong> Leftovers remain available outside the packets.</div>`;
  }
  return `<div class="review-banner good"><strong>All hard rules currently pass.</strong> Soft-score penalty: ${Number(report.score.total).toFixed(2)}.</div>`;
}

function renderReview() {
  const summary = byId("review-summary");
  const host = byId("packet-list");
  if (!state.payload || !state.layouts) {
    summary.innerHTML = `<div class="review-banner">Generate a build to inspect packet placements.</div>`;
    host.innerHTML = "";
    return;
  }
  summary.innerHTML = reviewMessage();
  if (state.dirty) {
    summary.insertAdjacentHTML("afterbegin", `<div class="review-banner warn"><strong>Unsaved placement edits.</strong> Recalculate and validate before audit or export.</div>`);
  }
  const questions = Object.fromEntries(state.payload.draft.questions.map((question) => [question.id, question]));
  host.innerHTML = state.payload.draft.packets.map((packet, packetIndex) => `
    <article class="packet-card">
      <header class="packet-header">
        <strong>${escapeHtml(packet.name)}</strong>
        <span>${state.layouts[packetIndex].tossups.length} tossups · ${state.layouts[packetIndex].bonuses.length} bonuses</span>
      </header>
      <div class="packet-body">
        ${renderQuestionColumn(state.layouts[packetIndex].tossups, "tossups", packetIndex, questions)}
        ${renderQuestionColumn(state.layouts[packetIndex].bonuses, "bonuses", packetIndex, questions)}
      </div>
    </article>`).join("");
}

function renderQuestionColumn(ids, type, packetIndex, questions) {
  return `<div class="question-column"><h4>${type} · ${ids.length}</h4>${ids.map((id, index) => {
    const question = questions[id];
    if (!question) return "";
    const prompt = question.type === "tossup" ? question.question : question.leadin;
    const answer = question.type === "tossup"
      ? question.answer
      : question.parts.map((part) => `${part.question} — ${part.answer}`).join(" · ");
    return `<div class="question-row">
      <span class="question-number">${String(index + 1).padStart(2, "0")}</span>
      <div class="question-main">
        <strong>${escapeHtml(question.id)}</strong>
        <p>${escapeHtml(prompt)}</p>
        <span class="topic-tag">${escapeHtml(question.category)} / ${escapeHtml(question.subcategory)}</span>
        <details><summary class="topic-tag">Answer/details</summary><p>${escapeHtml(answer)}</p></details>
      </div>
      <div class="question-actions">
        <button class="icon-button" title="Move up" aria-label="Move up" data-order="up" data-packet="${packetIndex}" data-type="${type}" data-id="${escapeHtml(id)}">↑</button>
        <button class="icon-button" title="Move down" aria-label="Move down" data-order="down" data-packet="${packetIndex}" data-type="${type}" data-id="${escapeHtml(id)}">↓</button>
        <select class="move-select" aria-label="Move question to packet" data-move="${escapeHtml(id)}" data-type="${type}" data-from="${packetIndex}">
          <option value="${packetIndex}">Move…</option>
          ${state.payload.draft.packets.map((packet, destination) => destination === packetIndex ? "" : `<option value="${destination}">${escapeHtml(packet.name)}</option>`).join("")}
        </select>
      </div>
    </div>`;
  }).join("")}</div>`;
}

function renderAudit(result) {
  const host = byId("audit-results");
  if (result.needs_clarification) {
    host.innerHTML = `<article class="card audit-card"><h3>Could not interpret that request</h3><p>${escapeHtml(result.clarification)}</p></article>`;
    return;
  }
  const hardErrors = result.hard_errors.length
    ? `<div class="review-banner error"><strong>Hard-rule violations</strong><ul>${result.hard_errors.map((error) => `<li>${escapeHtml(error)}</li>`).join("")}</ul></div>`
    : `<div class="review-banner good"><strong>No hard-rule violations</strong> · ${result.leftover_count} unassigned questions</div>`;
  const distribution = result.composition.map((item) => `
    <article class="card audit-card">
      <h3>${escapeHtml(item.label)} composition</h3>
      <p>${item.pool_target_count} of ${item.pool_eligible_count} tagged pool questions (${percent(item.pool_share)}), from ${item.pool_scoped_count} in scope. Across assigned packets, ${item.packet_target_count} of ${item.packet_eligible_count} tagged questions matched. Tag coverage: ${percent(item.tag_coverage)}. ${escapeHtml(item.note)}</p>
      <div class="audit-table-wrap"><table class="audit-table">
        <thead><tr><th>Packet</th><th>Matched</th><th>Tagged</th><th>In scope</th><th>Coverage</th><th>Share</th><th>vs pool</th><th>vs peer mean</th><th>Questions</th></tr></thead>
        <tbody>${item.packets.map((packet) => `<tr>
          <td>${packet.packet}</td><td>${packet.target_count}</td><td>${packet.eligible_count}</td><td>${packet.scoped_count}</td>
          <td>${percent(packet.tag_coverage)}</td><td>${percent(packet.share)}</td><td class="delta">${signedPercent(packet.difference_from_pool)}</td>
          <td class="delta">${signedPercent(packet.difference_from_peer_mean)}</td>
          <td>${packet.question_ids.map(escapeHtml).join(", ") || "—"}</td>
        </tr>`).join("")}</tbody>
      </table></div>
    </article>`).join("");
  const conflicts = result.likely_conflicts.length
    ? `<div class="conflict-list">${result.likely_conflicts.map((item) => `
      <div class="conflict-row"><strong>Packet ${item.packet}</strong>
        <span>${escapeHtml(item.first_id)} ↔ ${escapeHtml(item.second_id)} · ${escapeHtml(item.reason)}</span>
        <em>${Number(item.similarity).toFixed(3)}</em></div>`).join("")}</div>`
    : `<p>No candidate conflicts were found in the current layout.</p>`;
  host.innerHTML = `${hardErrors}${distribution}
    <article class="card audit-card"><h3>Likely conflicts to review</h3>
      <p>Top pairwise similarity candidates and adjacent same-category tossups. These are review signals, not automatic errors.</p>
      ${conflicts}
    </article>`;
}

function percent(value) { return `${(Number(value) * 100).toFixed(1)}%`; }
function signedPercent(value) {
  const number = Number(value) * 100;
  return `${number > 0 ? "+" : ""}${number.toFixed(1)} pp`;
}

function updateDemoGuide() {
  const guide = byId("demo-guide");
  if (!state.demo || state.demoStage >= demoStages.length) {
    guide.hidden = true;
    return;
  }
  const [view, instruction] = demoStages[state.demoStage];
  guide.hidden = false;
  guide.innerHTML = `<div><strong>Guided demo · Step ${state.demoStage + 2} of 6 · ${escapeHtml(titles[view])}</strong>${escapeHtml(instruction)}</div>
    <button id="demo-next">Next step →</button>`;
  byId("demo-next").addEventListener("click", () => {
    state.demoStage = Math.min(state.demoStage + 1, demoStages.length);
    if (state.demoStage < demoStages.length) showView(demoStages[state.demoStage][0]);
    updateDemoGuide();
  });
}

async function initialize() {
  try {
    [state.options, state.templates] = await Promise.all([
      api("/api/options"),
      api("/api/templates").then((result) => result.templates),
    ]);
    renderOptions();
    const select = byId("template-select");
    select.innerHTML = state.templates.map((entry, index) =>
      `<option value="${index}">${escapeHtml(entry.name)}</option>`
    ).join("");
    if (state.templates.length) {
      const winterIndex = state.templates.findIndex((entry) => entry.id === "acf-winter-final.json");
      const initialIndex = winterIndex >= 0 ? winterIndex : 0;
      select.value = String(initialIndex);
      loadTemplateForm(state.templates[initialIndex].template);
      byId("packet-count").value = defaultPacketCount(state.templates[initialIndex].id);
    }
  } catch (error) {
    setNotice(error.message, "error");
  }
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});
document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.go));
});

byId("csv-file").addEventListener("change", (event) => {
  state.selectedFile = event.target.files[0] || null;
  byId("import-csv").disabled = !state.selectedFile;
});
byId("import-csv").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!state.selectedFile) return;
  setBusy(button, true, "Importing…");
  try {
    const csv = await state.selectedFile.text();
    const pool = await api("/api/import", { csv, filename: state.selectedFile.name });
    poolLoaded(pool);
    setNotice(`Imported ${pool.tossup_count} tossups and ${pool.bonus_count} bonuses.`, "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("load-demo").addEventListener("click", async () => {
  const button = byId("load-demo");
  setBusy(button, true, "Loading sample…");
  try {
    const pool = await api("/api/demo", {});
    poolLoaded(pool);
    state.demo = true;
    state.demoStage = 0;
    showView("configure");
    updateDemoGuide();
    setNotice("Sample pool loaded. Follow the guided steps to generate and review a draft.", "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("template-select").addEventListener("change", (event) => {
  const entry = state.templates[Number(event.target.value)];
  if (entry) {
    loadTemplateForm(entry.template);
    byId("packet-count").value = defaultPacketCount(entry.id);
  }
});
byId("new-template").addEventListener("click", () => {
  byId("template-select").value = "";
  byId("template-name").value = "My packet template";
  byId("tossup-capacity").value = 20;
  byId("bonus-capacity").value = 20;
  byId("quota-list").innerHTML = "";
  byId("patterns-json").value = "[]";
  byId("leftover-tu").value = "";
  byId("leftover-bonus").value = "";
});
byId("add-quota").addEventListener("click", () => {
  byId("quota-list").insertAdjacentHTML("beforeend", quotaRow());
});
byId("quota-list").addEventListener("click", (event) => {
  if (event.target.classList.contains("remove-row")) event.target.closest(".quota-row").remove();
});
byId("add-category-pattern").addEventListener("click", () => {
  try {
    const patterns = JSON.parse(byId("patterns-json").value || "[]");
    const categories = byId("pattern-categories").value.split(",").map((item) => item.trim()).filter(Boolean);
    const tossups = Number(byId("pattern-tossups").value || 0);
    const bonuses = Number(byId("pattern-bonuses").value || 0);
    if (!categories.length || tossups + bonuses < 1) {
      throw new Error("Enter one or more categories and require at least one tossup or bonus.");
    }
    patterns.push({
      name: byId("pattern-name").value.trim() || `Category mix ${patterns.length + 1}`,
      categories,
      counts: { tossup: tossups, bonus: bonuses },
      distinct_categories: byId("pattern-distinct").checked,
    });
    byId("patterns-json").value = JSON.stringify(patterns, null, 2);
    setNotice("Category count rule added. Save or run the template to validate it.", "success");
  } catch (error) { setNotice(error.message, "error"); }
});
byId("template-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const template = JSON.parse(await file.text());
    if (template.schema_version !== 1) throw new Error("Unsupported template schema_version.");
    loadTemplateForm(template);
    byId("template-select").value = "";
    setNotice(`Loaded template “${template.name}”.`, "success");
  } catch (error) { setNotice(`Could not import template: ${error.message}`, "error"); }
  event.target.value = "";
});
byId("save-template").addEventListener("click", () => {
  try {
    const template = currentTemplateFromForm();
    const blob = new Blob([`${JSON.stringify(template, null, 2)}\n`], { type: "application/json" });
    download(blob, `${slug(template.name)}.json`);
    setNotice("Template JSON downloaded.", "success");
  } catch (error) { setNotice(error.message, "error"); }
});

byId("run-build").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setBusy(button, true, "Generating…");
  try {
    const template = currentTemplateFromForm();
    const solvers = [...document.querySelectorAll('input[name="solver"]:checked')].map((input) => input.value);
    const similarities = [...document.querySelectorAll('input[name="similarity"]:checked')].map((input) => input.value);
    const result = await api("/api/generate", {
      template,
      packet_count: Number(byId("packet-count").value),
      seed: Number(byId("seed").value),
      solvers,
      similarities,
      soft_weights: {
        adjacent_category: Number(byId("weight-adjacent").value),
        same_packet: Number(byId("weight-packet").value),
        nearby: Number(byId("weight-nearby").value),
        window: Number(byId("weight-window").value),
      },
    });
    updateRunState(result);
    showView("compare");
    setNotice(`Generated ${result.runs.length} comparable build${result.runs.length === 1 ? "" : "s"}.`, "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("comparison-results").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-select-run]");
  if (!button) return;
  if (state.dirty && !window.confirm("Discard the unrecalculated placement edits and switch comparison result?")) return;
  try {
    const payload = await api("/api/select-run", { run_index: Number(button.dataset.selectRun) });
    updateRunState(payload);
    showView("review");
  } catch (error) { setNotice(error.message, "error"); }
});

byId("packet-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-order]");
  if (!button || !state.layouts) return;
  const packet = Number(button.dataset.packet);
  const sequence = state.layouts[packet][button.dataset.type];
  const index = sequence.indexOf(button.dataset.id);
  const target = button.dataset.order === "up" ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= sequence.length) return;
  [sequence[index], sequence[target]] = [sequence[target], sequence[index]];
  state.dirty = true;
  renderReview();
});
byId("packet-list").addEventListener("change", (event) => {
  const select = event.target.closest("[data-move]");
  if (!select || !state.layouts) return;
  const source = Number(select.dataset.from);
  const destination = Number(select.value);
  const type = select.dataset.type;
  if (source === destination || !state.layouts[destination]) return;
  const sourceQuestions = state.layouts[source][type];
  const index = sourceQuestions.indexOf(select.dataset.move);
  if (index < 0) return;
  const [questionId] = sourceQuestions.splice(index, 1);
  state.layouts[destination][type].push(questionId);
  state.dirty = true;
  renderReview();
});
byId("apply-review").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!state.layouts) return;
  setBusy(button, true, "Validating…");
  try {
    const payload = await api("/api/review", { packets: state.layouts });
    updateRunState(payload);
    state.dirty = false;
    renderReview();
    setNotice("Placements renumbered and recalculated against hard rules and soft scores.", "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("run-audit").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setBusy(button, true, "Investigating…");
  try {
    if (state.dirty) {
      const payload = await api("/api/review", { packets: state.layouts });
      updateRunState(payload);
      state.dirty = false;
    }
    const result = await api("/api/audit", { request: byId("audit-request").value });
    renderAudit(result);
    if (result.needs_clarification) setNotice(result.clarification, "error");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});
byId("export-packets").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setBusy(button, true, "Preparing files…");
  try {
    if (state.dirty) {
      const payload = await api("/api/review", { packets: state.layouts });
      updateRunState(payload);
      state.dirty = false;
    }
    const result = await api("/api/export", {});
    result.files.forEach((file, index) => {
      window.setTimeout(() => {
        download(new Blob([file.content], { type: "application/json" }), file.filename);
      }, index * 180);
    });
    setNotice(`Prepared ${result.files.length} packet JSON file${result.files.length === 1 ? "" : "s"} for download.`, "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});

function download(blob, filename) {
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
}
function slug(value) {
  return String(value).normalize("NFKD").replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase() || "template";
}
function defaultPacketCount(templateId) {
  if (templateId === "acf-fall-final.json") return 8;
  if (templateId === "acf-winter-final.json" || templateId === "acf-winter-submitted.json") return 16;
  return 1;
}

initialize();

window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});
