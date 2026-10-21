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
  patterns: [],
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
    <div class="audit-table-wrap category-table-wrap">
      <table class="audit-table category-table">
        <thead><tr><th>Category</th><th class="num">Tossups</th><th class="num">Bonuses</th><th class="num">Subcategories</th><th>Subcategory list</th></tr></thead>
        <tbody>${Object.entries(pool.categories).map(([category, subs]) => {
          const counts = (pool.category_counts || {})[category] || { tossups: 0, bonuses: 0 };
          return `<tr><td><strong>${escapeHtml(category)}</strong></td><td class="num">${counts.tossups}</td><td class="num">${counts.bonuses}</td><td class="num">${subs.length}</td><td class="wrap">${subs.map(escapeHtml).join(", ")}</td></tr>`;
        }).join("")}</tbody>
        <tfoot><tr><td>Total</td><td class="num">${pool.tossup_count}</td><td class="num">${pool.bonus_count}</td><td class="num"></td><td></td></tr></tfoot>
      </table>
    </div>`;
  const categories = Object.keys(pool.categories);
  byId("category-options").innerHTML = categories.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  byId("subcategory-options").innerHTML = [...new Set(Object.values(pool.categories).flat())]
    .sort().map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  byId("wizard-run").disabled = false;
  prefillCategoryRows();
  renderPatterns();
  scheduleFeasibility();
  byId("config-pool-hint").innerHTML =
    `<strong>${categories.length} categories available</strong><br>${categories.slice(0, 8).map(escapeHtml).join(" · ")}${categories.length > 8 ? " · …" : ""}`;
}

function quotaRow(quota = {}) {
  const selector = quota.selector || {};
  return `<div class="quota-row">
    <input class="quota-category" list="category-options" value="${escapeHtml(selector.category || "")}" placeholder="Category" aria-label="Category">
    <input class="quota-subcategory" list="subcategory-options" value="${escapeHtml(selector.subcategory || "")}" placeholder="Subcategory (optional)" aria-label="Subcategory">
    <input class="quota-min" type="number" min="0" value="${Number(quota.minimum || 0)}" aria-label="Minimum">
    <input class="quota-max" type="number" min="0" value="${quota.maximum == null ? "" : Number(quota.maximum)}" placeholder="Max" aria-label="Maximum">
    <button type="button" class="remove-row" aria-label="Remove quota">×</button>
  </div>`;
}

function currentTemplateFromForm() {
  const quotas = ["tossup", "bonus"].flatMap((type) =>
    [...document.querySelectorAll(`#${type}-quota-list .quota-row`)].map((row, index) => {
      const category = row.querySelector(".quota-category").value.trim();
      if (!category) throw new Error(`${type === "tossup" ? "Tossup" : "Bonus"} quota ${index + 1} needs a category.`);
      const maximumValue = row.querySelector(".quota-max").value;
      return {
        selector: {
          question_type: type,
          category,
          subcategory: row.querySelector(".quota-subcategory").value.trim() || null,
        },
        minimum: Number(row.querySelector(".quota-min").value || 0),
        maximum: maximumValue === "" ? null : Number(maximumValue),
      };
    })
  );
  const patterns = state.patterns.map((rule, index) => {
    if (isSimpleRule(rule)) {
      const problem = simpleRuleProblem(rule);
      if (problem) throw new Error(`Distribution pattern ${index + 1}: ${problem}`);
    }
    return rule;
  });
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
  for (const type of ["tossup", "bonus"]) {
    byId(`${type}-quota-list`).innerHTML = (template.quotas || [])
      .filter((quota) => quota.selector?.question_type === type)
      .map(quotaRow)
      .join("");
  }
  setPatterns(structuredClone(template.allowed_patterns || []));
  const leftovers = template.leftover_bounds || [];
  const tu = leftovers.find((item) => item.question_type === "tossup");
  const bonus = leftovers.find((item) => item.question_type === "bonus");
  byId("leftover-tu").value = tu?.maximum ?? "";
  byId("leftover-bonus").value = bonus?.maximum ?? "";
}

let feasibilityTimer;
function scheduleFeasibility() {
  window.clearTimeout(feasibilityTimer);
  feasibilityTimer = window.setTimeout(updateFeasibility, 350);
}
let feasibilitySequence = 0;
async function updateFeasibility() {
  const box = byId("feasibility");
  if (!state.pool) {
    box.className = "hint-box feasibility";
    box.textContent = "Import a pool to check feasibility.";
    return;
  }
  const sequence = ++feasibilitySequence;
  let template;
  try { template = currentTemplateFromForm(); } catch (error) {
    box.className = "hint-box feasibility bad";
    box.textContent = error.message;
    return;
  }
  const packetCount = Number(byId("packet-count").value);
  if (!Number.isInteger(packetCount) || packetCount < 1) {
    box.className = "hint-box feasibility bad";
    box.textContent = "Enter a packet count of 1 or more.";
    return;
  }
  try {
    const result = await api("/api/feasibility", { template, packet_count: packetCount });
    if (sequence !== feasibilitySequence) return;
    const short = result.requirements.filter((row) => !row.ok);
    const messages = result.errors.length ? result.errors : short.map((row) => `${row.label}: need ${row.needed}, pool has ${row.available}`);
    box.className = `hint-box feasibility ${result.feasible ? "good" : "bad"}`;
    box.innerHTML = `<strong>${result.feasible ? "Pool can support this template" : "Pool cannot support this template"}</strong><br>` +
      `Up to ${result.max_packets} packet${result.max_packets === 1 ? "" : "s"} fit these minimums.` +
      (result.max_packets > 0 && result.max_packets !== packetCount
        ? ` <button type="button" class="linklike" id="use-max-packets" data-count="${result.max_packets}">Use ${result.max_packets}</button>` : "") +
      (messages.length ? `<ul>${messages.slice(0, 8).map((message) => `<li>${escapeHtml(message)}</li>`).join("")}</ul>` : "");
  } catch (error) {
    if (sequence !== feasibilitySequence) return;
    box.className = "hint-box feasibility bad";
    box.textContent = error.message;
  }
}

function catRow(category = {}) {
  const subs = (category.subs || []).map(subRow).join("");
  return `<div class="cat-row">
    <div class="cat-head">
      <input class="cat-name" list="category-options" value="${escapeHtml(category.name || "")}" placeholder="Category" aria-label="Major category">
      <input class="cat-tu" type="number" min="0" value="${Number(category.tossups || 0)}" aria-label="Tossups per packet">
      <input class="cat-bonus" type="number" min="0" value="${Number(category.bonuses || 0)}" aria-label="Bonuses per packet">
      <button type="button" class="button small secondary cat-add-sub">+ Subcategory</button>
      <button type="button" class="remove-row cat-remove" aria-label="Remove category">×</button>
    </div>
    <div class="cat-subs">${subs}</div>
    <div class="sub-labels"><span>Subcategory</span><span>TU min</span><span>TU max</span><span>B min</span><span>B max</span><span></span></div>
    <div class="cat-error" hidden></div>
  </div>`;
}

function subRow(sub = {}) {
  const value = (number) => (number == null ? "" : Number(number));
  return `<div class="sub-row">
    <input class="sub-name" list="subcategory-options" value="${escapeHtml(sub.name || "")}" placeholder="Subcategory" aria-label="Subcategory">
    <input class="sub-tmin" type="number" min="0" value="${value(sub.tmin ?? 0)}" aria-label="Tossup minimum">
    <input class="sub-tmax" type="number" min="0" value="${value(sub.tmax)}" placeholder="max" aria-label="Tossup maximum">
    <input class="sub-bmin" type="number" min="0" value="${value(sub.bmin ?? 0)}" aria-label="Bonus minimum">
    <input class="sub-bmax" type="number" min="0" value="${value(sub.bmax)}" placeholder="max" aria-label="Bonus maximum">
    <button type="button" class="remove-row sub-remove" aria-label="Remove subcategory">×</button>
  </div>`;
}

function readCategoryRows() {
  return [...document.querySelectorAll(".cat-row")].map((row) => {
    const optional = (input) => (input.value === "" ? null : Number(input.value));
    return {
      element: row,
      name: row.querySelector(".cat-name").value.trim(),
      tossups: Number(row.querySelector(".cat-tu").value || 0),
      bonuses: Number(row.querySelector(".cat-bonus").value || 0),
      subs: [...row.querySelectorAll(".sub-row")].map((sub) => ({
        name: sub.querySelector(".sub-name").value.trim(),
        tmin: Number(sub.querySelector(".sub-tmin").value || 0),
        tmax: optional(sub.querySelector(".sub-tmax")),
        bmin: Number(sub.querySelector(".sub-bmin").value || 0),
        bmax: optional(sub.querySelector(".sub-bmax")),
      })),
    };
  });
}

function validateCategoryRows(rows) {
  let valid = rows.length > 0;
  const seen = new Set();
  rows.forEach((row) => {
    const problems = [];
    if (!row.name) problems.push("Enter a category name.");
    else if (seen.has(row.name.toLowerCase())) problems.push("This category is listed twice.");
    seen.add(row.name.toLowerCase());
    for (const [label, count, minKey, maxKey] of [["Tossup", row.tossups, "tmin", "tmax"], ["Bonus", row.bonuses, "bmin", "bmax"]]) {
      const minimumTotal = row.subs.reduce((sum, sub) => sum + sub[minKey], 0);
      if (minimumTotal > count) problems.push(`${label} subcategory minimums (${minimumTotal}) exceed the ${count} per packet for this category.`);
      row.subs.forEach((sub) => {
        if (sub[maxKey] != null && sub[maxKey] < sub[minKey]) problems.push(`${label} maximum is below minimum for “${sub.name || "subcategory"}”.`);
      });
    }
    if (row.subs.some((sub) => !sub.name)) problems.push("Every subcategory needs a name.");
    const names = row.subs.map((sub) => sub.name.toLowerCase());
    if (new Set(names).size !== names.length) problems.push("A subcategory is listed twice.");
    const box = row.element.querySelector(".cat-error");
    box.hidden = problems.length === 0;
    box.innerHTML = [...new Set(problems)].map(escapeHtml).join("<br>");
    if (problems.length) valid = false;
  });
  return valid;
}

function updateCategorySummary() {
  const rows = readCategoryRows();
  const tossups = rows.reduce((sum, row) => sum + row.tossups, 0);
  const bonuses = rows.reduce((sum, row) => sum + row.bonuses, 0);
  byId("cat-summary").textContent = `Totals: ${tossups} tossups and ${bonuses} bonuses per packet.`;
  byId("cat-apply").disabled = !state.pool || rows.length === 0;
}

function prefillCategoryRows() {
  if (!state.pool) return;
  byId("cat-rows").innerHTML = Object.keys(state.pool.categories).map((name) => catRow({ name })).join("");
  updateCategorySummary();
}

function applyCategoryRows() {
  const rows = readCategoryRows();
  if (!validateCategoryRows(rows)) {
    setNotice("Fix the highlighted category rows before applying.", "error");
    return;
  }
  const quotas = [];
  for (const [type, countKey, minKey, maxKey] of [["tossup", "tossups", "tmin", "tmax"], ["bonus", "bonuses", "bmin", "bmax"]]) {
    for (const row of rows) {
      if (row[countKey] > 0) quotas.push({ selector: { question_type: type, category: row.name, subcategory: null }, minimum: row[countKey], maximum: row[countKey] });
      for (const sub of row.subs) {
        if (sub[minKey] > 0 || sub[maxKey] != null) {
          quotas.push({ selector: { question_type: type, category: row.name, subcategory: sub.name }, minimum: sub[minKey], maximum: sub[maxKey] });
        }
      }
    }
  }
  const patterns = structuredClone(state.patterns);
  const template = {
    schema_version: 1,
    name: byId("template-name").value.trim() || "Custom template",
    tossup_capacity: rows.reduce((sum, row) => sum + row.tossups, 0),
    bonus_capacity: rows.reduce((sum, row) => sum + row.bonuses, 0),
    quotas,
    allowed_patterns: patterns,
    leftover_bounds: [
      { question_type: "tossup", minimum: 0, maximum: byId("leftover-tu").value === "" ? null : Number(byId("leftover-tu").value) },
      { question_type: "bonus", minimum: 0, maximum: byId("leftover-bonus").value === "" ? null : Number(byId("leftover-bonus").value) },
    ],
  };
  loadTemplateForm(template);
  byId("template-select").value = "";
  scheduleFeasibility();
  setNotice("Category rules applied to the quota list. Review them below.", "success");
}

function isSimpleRule(rule) {
  return rule && Array.isArray(rule.categories) && rule.counts && !rule.groups;
}

function simpleRuleProblem(rule) {
  const tossups = Number(rule.counts.tossup || 0);
  const bonuses = Number(rule.counts.bonus || 0);
  if (!rule.categories.length) return "choose at least one category.";
  if (tossups + bonuses < 1) return "require at least one tossup or bonus.";
  if (rule.distinct_categories && Math.max(tossups, bonuses) > rule.categories.length) {
    return "with different categories, each question type needs at least as many categories as questions.";
  }
  return "";
}

function plural(count, noun) { return `${count} ${noun}${count === 1 ? "" : "s"}`; }

function ruleSentence(rule) {
  const tossups = Number(rule.counts.tossup || 0);
  const bonuses = Number(rule.counts.bonus || 0);
  const parts = [];
  if (tossups) parts.push(plural(tossups, "tossup"));
  if (bonuses) parts.push(plural(bonuses, "bonus").replace("bonuss", "bonuses"));
  const list = rule.categories.length ? rule.categories.join(", ") : "…";
  return `Each packet needs ${parts.join(" and ") || "no questions"} from ${list}${rule.distinct_categories ? ", each from a different category" : ""}.`;
}

function describeOtherRule(rule) {
  if (rule.groups) {
    const counts = rule.counts || {};
    return `Group rule: ${rule.groups.length} category group${rule.groups.length === 1 ? "" : "s"}, ${counts.tossup ?? 0} tossups and ${counts.bonus ?? 0} bonuses per packet. Edit in Advanced JSON.`;
  }
  if (rule.selectors) return `Exact combinations rule: ${(rule.patterns || []).length} allowed pattern(s) over ${rule.selectors.length} selector(s). Edit in Advanced JSON.`;
  return "Custom rule. Edit in Advanced JSON.";
}

function syncPatternJson() {
  byId("patterns-json").value = JSON.stringify(state.patterns, null, 2);
  byId("patterns-json-error").hidden = true;
}

function setPatterns(patterns) {
  state.patterns = Array.isArray(patterns) ? patterns : [];
  renderPatterns();
}

function patternCard(rule, index) {
  if (!isSimpleRule(rule)) {
    return `<div class="pattern-card readonly" data-index="${index}">
      <div class="pattern-top"><strong>${escapeHtml(rule.name || "Unnamed rule")}</strong><button type="button" class="remove-row pattern-remove" aria-label="Remove rule">×</button></div>
      <p class="small muted-text">${escapeHtml(describeOtherRule(rule))}</p></div>`;
  }
  const known = state.pool ? Object.keys(state.pool.categories) : [];
  const options = [...new Set([...known, ...rule.categories])];
  const chips = options.map((name) => `<label class="chip"><input type="checkbox" class="pattern-cat" value="${escapeHtml(name)}" ${rule.categories.includes(name) ? "checked" : ""}>${escapeHtml(name)}</label>`).join("");
  return `<div class="pattern-card" data-index="${index}">
    <div class="pattern-top">
      <input type="text" class="pattern-name" value="${escapeHtml(rule.name || "")}" placeholder="Rule name (optional)" aria-label="Rule name">
      <button type="button" class="remove-row pattern-remove" aria-label="Remove rule">×</button>
    </div>
    <div class="pattern-counts">
      <label>Tossups <input type="number" min="0" class="pattern-tu" value="${Number(rule.counts.tossup || 0)}"></label>
      <label>Bonuses <input type="number" min="0" class="pattern-bonus" value="${Number(rule.counts.bonus || 0)}"></label>
      <label class="compact-check"><input type="checkbox" class="pattern-distinct" ${rule.distinct_categories ? "checked" : ""}> Each from a different category</label>
    </div>
    <div class="chips" role="group" aria-label="Categories">${chips || '<span class="small muted-text">Import a pool to pick categories, or add one below.</span>'}</div>
    <div class="add-custom"><input type="text" class="pattern-custom" placeholder="Add another category name" aria-label="Custom category" list="category-options"><button type="button" class="button small secondary pattern-add-cat">Add</button></div>
    <div class="pattern-sentence"></div>
    <div class="cat-error" hidden></div>
  </div>`;
}

function refreshPatternCard(card) {
  const rule = state.patterns[Number(card.dataset.index)];
  if (!isSimpleRule(rule)) return;
  card.querySelector(".pattern-sentence").textContent = ruleSentence(rule);
  const problem = simpleRuleProblem(rule);
  const box = card.querySelector(".cat-error");
  box.hidden = !problem;
  box.textContent = problem ? `Needs attention: ${problem}` : "";
}

function renderPatterns() {
  const list = byId("pattern-list");
  list.innerHTML = state.patterns.length
    ? state.patterns.map(patternCard).join("")
    : '<p class="small muted-text">No additional patterns. Add one if some categories should be combined or kept distinct within each packet.</p>';
  list.querySelectorAll(".pattern-card").forEach(refreshPatternCard);
  syncPatternJson();
}

function updatePatternFromCard(card) {
  const rule = state.patterns[Number(card.dataset.index)];
  if (!isSimpleRule(rule)) return;
  rule.name = card.querySelector(".pattern-name").value.trim() || `Category mix ${Number(card.dataset.index) + 1}`;
  rule.counts = {
    tossup: Number(card.querySelector(".pattern-tu").value || 0),
    bonus: Number(card.querySelector(".pattern-bonus").value || 0),
  };
  rule.distinct_categories = card.querySelector(".pattern-distinct").checked;
  rule.categories = [...card.querySelectorAll(".pattern-cat:checked")].map((input) => input.value);
  refreshPatternCard(card);
  syncPatternJson();
  scheduleFeasibility();
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
    select.innerHTML = `<option value="" hidden>Custom (your edits)</option>
      <optgroup label="Pre-built templates">${state.templates.map((entry, index) =>
        `<option value="${index}">${escapeHtml(entry.name)}</option>`).join("")}</optgroup>
      <optgroup label="Generate from your imported pool">
        <option value="${START_MIRROR}">Suggest: mirror the pool's category mix</option>
        <option value="${START_CATEGORIES}">Suggest: build by category and subcategory</option>
      </optgroup>
      <optgroup label="Build your own"><option value="${START_SCRATCH}">Start from scratch</option></optgroup>`;
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
    const content = await state.selectedFile.text();
    const isJson = /\.json$/i.test(state.selectedFile.name);
    const pool = isJson
      ? await api("/api/import-json", { json: content, filename: state.selectedFile.name })
      : await api("/api/import", { csv: content, filename: state.selectedFile.name });
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

const START_MIRROR = "start:mirror";
const START_CATEGORIES = "start:categories";
const START_SCRATCH = "start:scratch";

function showWizard(mode) {
  const categories = mode === "categories";
  byId("wizard").hidden = !mode;
  byId("wizard-mirror").hidden = categories;
  byId("wizard-categories").hidden = !categories;
  if (categories && !document.querySelector(".cat-row")) prefillCategoryRows();
}

byId("template-select").addEventListener("change", (event) => {
  const value = event.target.value;
  showWizard(value === START_MIRROR ? "mirror" : value === START_CATEGORIES ? "categories" : "");
  if (value === START_SCRATCH) {
    byId("template-name").value = "My packet template";
    byId("tossup-capacity").value = 20;
    byId("bonus-capacity").value = 20;
    byId("tossup-quota-list").innerHTML = "";
    byId("bonus-quota-list").innerHTML = "";
    setPatterns([]);
    byId("leftover-tu").value = "";
    byId("leftover-bonus").value = "";
    return;
  }
  const entry = state.templates[Number(value)];
  if (value !== "" && entry) {
    loadTemplateForm(entry.template);
    byId("packet-count").value = defaultPacketCount(entry.id);
  }
});
byId("feasibility").addEventListener("click", (event) => {
  if (event.target.id === "use-max-packets") {
    byId("packet-count").value = event.target.dataset.count;
    scheduleFeasibility();
  }
});
byId("view-configure").addEventListener("input", scheduleFeasibility);
byId("view-configure").addEventListener("click", (event) => {
  if (event.target.closest("#add-tossup-quota, #add-bonus-quota, .remove-row")) scheduleFeasibility();
});
byId("template-select").addEventListener("change", scheduleFeasibility);
byId("template-file").addEventListener("change", () => window.setTimeout(scheduleFeasibility, 0));
byId("cat-add").addEventListener("click", () => {
  byId("cat-rows").insertAdjacentHTML("beforeend", catRow());
  updateCategorySummary();
});
byId("cat-apply").addEventListener("click", applyCategoryRows);
byId("cat-rows").addEventListener("input", updateCategorySummary);
byId("cat-rows").addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("cat-add-sub")) target.closest(".cat-row").querySelector(".cat-subs").insertAdjacentHTML("beforeend", subRow());
  else if (target.classList.contains("sub-remove")) target.closest(".sub-row").remove();
  else if (target.classList.contains("cat-remove")) target.closest(".cat-row").remove();
  else return;
  updateCategorySummary();
});
byId("wizard-run").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setBusy(button, true, "Suggesting…");
  try {
    const result = await api("/api/suggest-template", {
      name: byId("template-name").value.trim() || "Suggested template",
      packet_count: Number(byId("packet-count").value),
      tossup_capacity: Number(byId("wizard-tossups").value),
      bonus_capacity: Number(byId("wizard-bonuses").value),
      tolerance: Number(byId("wizard-tolerance").value),
    });
    loadTemplateForm(result.template);
    byId("template-select").value = "";
    scheduleFeasibility();
    setNotice("Suggested quotas filled in. Review and adjust them before continuing.", "success");
  } catch (error) { setNotice(error.message, "error"); }
  finally { setBusy(button, false); }
});
byId("duplicate-template").addEventListener("click", () => {
  try {
    const template = currentTemplateFromForm();
    template.name = `${template.name} (copy)`;
    loadTemplateForm(template);
    byId("template-select").value = "";
    setNotice("Template duplicated. Rename it and edit freely.", "success");
  } catch (error) { setNotice(error.message, "error"); }
});
byId("reset-template").addEventListener("click", () => {
  const value = byId("template-select").value;
  const entry = /^\d+$/.test(value) ? state.templates[Number(value)] : null;
  if (!entry) { setNotice("Choose a pre-built template as your starting point to reset to.", "error"); return; }
  loadTemplateForm(entry.template);
  scheduleFeasibility();
  setNotice(`Reset to “${entry.template.name}”.`, "success");
});
for (const type of ["tossup", "bonus"]) {
  byId(`add-${type}-quota`).addEventListener("click", () => {
    byId(`${type}-quota-list`).insertAdjacentHTML("beforeend", quotaRow());
  });
  byId(`${type}-quota-list`).addEventListener("click", (event) => {
    if (event.target.classList.contains("remove-row")) event.target.closest(".quota-row").remove();
  });
}
byId("add-pattern").addEventListener("click", () => {
  state.patterns.push({ name: `Category mix ${state.patterns.length + 1}`, categories: [], counts: { tossup: 1, bonus: 1 }, distinct_categories: false });
  renderPatterns();
  byId("pattern-list").lastElementChild.querySelector(".pattern-name").focus();
});
byId("pattern-list").addEventListener("input", (event) => {
  const card = event.target.closest(".pattern-card");
  if (card && !event.target.classList.contains("pattern-custom")) updatePatternFromCard(card);
});
byId("pattern-list").addEventListener("click", (event) => {
  const card = event.target.closest(".pattern-card");
  if (!card) return;
  const index = Number(card.dataset.index);
  if (event.target.classList.contains("pattern-remove")) {
    state.patterns.splice(index, 1);
    renderPatterns();
    scheduleFeasibility();
  } else if (event.target.classList.contains("pattern-add-cat")) {
    const input = card.querySelector(".pattern-custom");
    const name = input.value.trim();
    const rule = state.patterns[index];
    if (name && isSimpleRule(rule) && !rule.categories.includes(name)) {
      rule.categories.push(name);
      renderPatterns();
      scheduleFeasibility();
    }
  }
});
byId("apply-patterns-json").addEventListener("click", () => {
  const box = byId("patterns-json-error");
  try {
    const parsed = JSON.parse(byId("patterns-json").value || "[]");
    if (!Array.isArray(parsed) || parsed.some((rule) => !rule || typeof rule !== "object" || Array.isArray(rule))) {
      throw new Error("Rules must be a JSON array of objects.");
    }
    setPatterns(parsed);
    scheduleFeasibility();
    setNotice("Distribution patterns updated from JSON.", "success");
  } catch (error) {
    box.hidden = false;
    box.textContent = `Not applied: ${error.message}`;
  }
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
    const selectedValue = byId("template-select").value;
    const selectedPreset = /^\d+$/.test(selectedValue) ? state.templates[Number(selectedValue)] : null;
    if (selectedPreset && slug(template.name) === slug(selectedPreset.template.name)) {
      throw new Error(`Choose a different template name before downloading; “${selectedPreset.template.name}” is a pre-built template filename.`);
    }
    const blob = new Blob([`${JSON.stringify(template, null, 2)}\n`], { type: "application/json" });
    download(blob, `${slug(template.name)}.json`);
    setNotice("Template JSON downloaded.", "success");
  } catch (error) { setNotice(error.message, "error"); }
});

byId("copy-tossup-quotas").addEventListener("click", () => {
  const tossupRows = [...byId("tossup-quota-list").querySelectorAll(".quota-row")];
  const bonusList = byId("bonus-quota-list");
  if (!tossupRows.length) {
    setNotice("Add at least one tossup quota before reusing its distribution for bonuses.", "error");
    return;
  }
  if (tossupRows.some((row) => !row.querySelector(".quota-category").value.trim())) {
    setNotice("Complete every tossup category before copying its distribution to bonuses.", "error");
    return;
  }
  if (bonusList.querySelector(".quota-row") && !window.confirm("Replace all current bonus quotas with copies of the tossup categories, subcategories, minimums, and maximums?")) {
    return;
  }
  const quotas = tossupRows.map((row) => ({
    selector: {
      question_type: "bonus",
      category: row.querySelector(".quota-category").value.trim(),
      subcategory: row.querySelector(".quota-subcategory").value.trim() || null,
    },
    minimum: Number(row.querySelector(".quota-min").value || 0),
    maximum: row.querySelector(".quota-max").value === "" ? null : Number(row.querySelector(".quota-max").value),
  }));
  bonusList.innerHTML = quotas.map(quotaRow).join("");
  scheduleFeasibility();
  setNotice("Bonus quotas now match the tossup categories, subcategories, minimums, and maximums.", "success");
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
