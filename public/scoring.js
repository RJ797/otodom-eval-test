const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());

const state = {
  scorer: localStorage.getItem("scorer") || "",
  runId: localStorage.getItem("runId") || "",
  results: [],
  index: 0,
  current: null,
  reveal: false,
  range: { min: 1, max: 10 },
};

function toast(msg, kind = "ok") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  setTimeout(() => el.classList.add("hidden"), 1800);
}

async function init() {
  $("scorer").value = state.scorer;

  const health = await api("/api/health").catch(() => null);
  if (health && health.score_min) state.range = { min: health.score_min, max: health.score_max };
  if (health && !health.mongo_configured) {
    toast("MongoDB not configured on server", "err");
  }

  const { runs } = await api("/api/runs").catch(() => ({ runs: [] }));
  const sel = $("runSelect");
  sel.innerHTML = '<option value="">— select run —</option>';
  runs.forEach((r) => {
    const opt = document.createElement("option");
    opt.value = r.id;
    const c = r.counts || {};
    opt.textContent = `${r.name || r.id}  (${c.completed || 0}/${c.total || 0})`;
    if (r.id === state.runId) opt.selected = true;
    sel.appendChild(opt);
  });

  $("scorer").addEventListener("change", (e) => {
    state.scorer = e.target.value.trim();
    localStorage.setItem("scorer", state.scorer);
    if (state.runId) loadRun();
  });
  sel.addEventListener("change", (e) => {
    state.runId = e.target.value;
    localStorage.setItem("runId", state.runId);
    loadRun();
  });
  $("revealLabels").addEventListener("change", (e) => {
    state.reveal = e.target.checked;
    applyReveal();
  });
  $("prevBtn").addEventListener("click", () => loadImage(state.index - 1));
  $("saveNextBtn").addEventListener("click", saveAndNext);
  $("summaryBtn").addEventListener("click", showSummary);
  $("closeSummary").addEventListener("click", () => $("summaryModal").classList.add("hidden"));

  if (state.runId) loadRun();
}

async function loadRun() {
  if (!state.runId) return;
  const scorer = encodeURIComponent(state.scorer || "");
  const data = await api(`/api/runs/${state.runId}/results?scorer=${scorer}`);
  state.results = data.results || [];
  updateProgress();
  if (!state.results.length) {
    $("card").classList.add("hidden");
    $("navbar").classList.add("hidden");
    $("empty").classList.remove("hidden");
    $("empty").textContent = "No results in this run yet.";
    return;
  }
  const firstUnscored = state.results.findIndex((r) => !r.scored_by_me);
  loadImage(firstUnscored >= 0 ? firstUnscored : 0);
}

function updateProgress() {
  const done = state.results.filter((r) => r.scored_by_me).length;
  const total = state.results.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("progress").innerHTML = `<div class="bar" style="width:${pct}%"></div>`;
}

async function loadImage(index) {
  if (index < 0 || index >= state.results.length) return;
  state.index = index;
  const meta = state.results[index];
  const scorer = encodeURIComponent(state.scorer || "");
  const res = await api(
    `/api/runs/${state.runId}/results/${meta.image_id}?scorer=${scorer}`
  );
  state.current = res;

  $("empty").classList.add("hidden");
  $("card").classList.remove("hidden");
  $("navbar").classList.remove("hidden");

  $("inputImg").src = res.input_url || "";
  $("promptText").textContent = res.prompt || "(no prompt)";
  renderOutputs(res);

  $("prevBtn").disabled = index === 0;
  $("navInfo").textContent = `Image ${meta.image_id} · ${index + 1}/${state.results.length}`;
}

function renderOutputs(res) {
  const wrap = $("outputs");
  wrap.innerHTML = "";
  (res.outputs || []).forEach((o) => {
    const my = (res.my_scores || {})[o.variant] || {};
    const card = document.createElement("div");
    card.className = "out-card";
    card.dataset.variant = o.variant;

    const meta = o.status === "ok"
      ? `model: ${o.model || "?"}${o.thinking_level ? " · " + o.thinking_level : ""} · ${o.time_taken_ms ?? "?"} ms${o.cost_usd != null ? " · $" + o.cost_usd : ""}${o.token_usage && o.token_usage.total != null ? " · " + o.token_usage.total + " tok" : ""}`
      : `ERROR: ${o.error || "failed"}`;

    card.innerHTML = `
      <div class="out-head">
        <span class="out-label">${o.label}</span>
        <span class="out-variant" style="display:none">${o.variant}</span>
      </div>
      ${o.image_url ? `<img class="out-img" src="${o.image_url}" alt="${o.label}" />` : `<div class="out-err">${o.error || "no image"}</div>`}
      <div class="out-meta">${meta}</div>
      <div class="score-row">
        <label>Score (${state.range.min}-${state.range.max})</label>
        <input class="score-input" type="number" min="${state.range.min}" max="${state.range.max}" value="${my.value ?? ""}" />
      </div>
      <textarea class="comment" placeholder="comment (optional)">${my.comment || ""}</textarea>
      <div class="best-row">
        <input type="radio" name="best" value="${o.variant}" ${res.my_best_pick === o.variant ? "checked" : ""} />
        <span>best</span>
      </div>
    `;
    wrap.appendChild(card);
  });
  applyReveal();
}

function applyReveal() {
  document.querySelectorAll(".out-variant").forEach((el) => {
    el.style.display = state.reveal ? "inline" : "none";
  });
  document.querySelectorAll(".out-meta").forEach((el) => {
    el.classList.toggle("show", state.reveal);
  });
}

async function saveAndNext() {
  if (!state.scorer) {
    toast("Enter your name first", "err");
    return;
  }
  const scores = {};
  document.querySelectorAll(".out-card").forEach((card) => {
    const variant = card.dataset.variant;
    const val = card.querySelector(".score-input").value;
    const comment = card.querySelector(".comment").value;
    if (val !== "") scores[variant] = { value: Number(val), comment };
  });
  const bestEl = document.querySelector('input[name="best"]:checked');
  const best_pick = bestEl ? bestEl.value : null;

  if (Object.keys(scores).length === 0) {
    toast("Score at least one output", "err");
    return;
  }

  const meta = state.results[state.index];
  const resp = await api(
    `/api/runs/${state.runId}/results/${meta.image_id}/score`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scorer: state.scorer, scores, best_pick }),
    }
  ).catch(() => null);

  if (!resp || !resp.ok) {
    toast("Save failed", "err");
    return;
  }
  toast("Saved");
  state.results[state.index].scored_by_me = true;
  updateProgress();

  const nextUnscored = state.results.findIndex((r, i) => i > state.index && !r.scored_by_me);
  if (nextUnscored >= 0) loadImage(nextUnscored);
  else if (state.index + 1 < state.results.length) loadImage(state.index + 1);
  else toast("All images scored!");
}

async function showSummary() {
  if (!state.runId) return;
  const data = await api(`/api/runs/${state.runId}/summary`);
  const rows = Object.entries(data.variants || {})
    .map(
      ([v, s]) => `<tr>
        <td>${v}</td>
        <td>${s.avg_score ?? "—"}</td>
        <td>${s.score_stdev ?? "—"}</td>
        <td>${s.n_scored}</td>
        <td>${s.wins}</td>
        <td>${s.avg_latency_ms ?? "—"}</td>
        <td>${s.p95_latency_ms ?? "—"}</td>
        <td>${s.avg_cost_usd != null ? "$" + s.avg_cost_usd : "—"}</td>
        <td>${s.total_cost_usd != null ? "$" + s.total_cost_usd : "—"}</td>
        <td>${s.n_ok}/${s.n_ok + s.n_err}</td>
      </tr>`
    )
    .join("");
  $("summaryContent").innerHTML = `
    <p style="color:var(--muted);font-size:13px">${data.n_images} images</p>
    <table>
      <thead><tr>
        <th>variant</th><th>avg</th><th>stdev</th><th>n scored</th><th>wins</th>
        <th>avg ms</th><th>p95 ms</th><th>avg cost</th><th>total cost</th><th>ok</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  $("summaryModal").classList.remove("hidden");
}

init();
