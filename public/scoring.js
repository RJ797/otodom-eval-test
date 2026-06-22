const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());

const state = {
  scorer: localStorage.getItem("scorer") || "",
  runId: localStorage.getItem("runId") || "",
  results: [],
  index: 0,
  current: null,
  reveal: localStorage.getItem("reveal") === "1",
  range: { min: 1, max: 10 },
};

function toast(msg, kind = "ok") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 1800);
}

// 1-3 red, 4-5 orange, 6-7 amber, 8-10 green
function scoreColor(v) {
  if (v <= 3) return "#fb7185";
  if (v <= 5) return "#fb923c";
  if (v <= 7) return "#fbbf24";
  return "#34d399";
}

async function init() {
  $("scorer").value = state.scorer;
  $("revealLabels").checked = state.reveal;

  const health = await api("/api/health").catch(() => null);
  if (health && health.score_min) state.range = { min: health.score_min, max: health.score_max };
  if (health && !health.mongo_configured) toast("MongoDB not configured on server", "err");

  await loadRuns();

  $("scorer").addEventListener("change", (e) => {
    state.scorer = e.target.value.trim();
    localStorage.setItem("scorer", state.scorer);
    if (state.runId) loadRun();
  });
  $("runSelect").addEventListener("change", (e) => {
    state.runId = e.target.value;
    localStorage.setItem("runId", state.runId);
    loadRun();
  });
  $("revealLabels").addEventListener("change", (e) => {
    state.reveal = e.target.checked;
    localStorage.setItem("reveal", state.reveal ? "1" : "0");
    applyReveal();
  });
  $("prevBtn").addEventListener("click", () => loadImage(state.index - 1));
  $("saveNextBtn").addEventListener("click", saveAndNext);
  $("summaryBtn").addEventListener("click", showSummary);
  $("closeSummary").addEventListener("click", () => $("summaryModal").classList.add("hidden"));
  $("lightbox").addEventListener("click", () => $("lightbox").classList.add("hidden"));
  document.addEventListener("keydown", onKey);

  if (state.runId) loadRun();
}

async function loadRuns() {
  const { runs } = await api("/api/runs").catch(() => ({ runs: [] }));
  const sel = $("runSelect");
  sel.innerHTML = '<option value="">— select run —</option>';
  runs.forEach((r) => {
    const opt = document.createElement("option");
    opt.value = r.id;
    const c = r.counts || {};
    opt.textContent = `${r.name || r.id} (${r.id})  ·  ${c.completed || 0}/${c.total || 0}`;
    if (r.id === state.runId) opt.selected = true;
    sel.appendChild(opt);
  });
}

async function loadRun() {
  if (!state.runId) return;
  const scorer = encodeURIComponent(state.scorer || "");
  const data = await api(`/api/runs/${state.runId}/results?scorer=${scorer}`);
  state.results = data.results || [];
  updateProgress();
  if (!state.results.length) {
    showCard(false);
    $("empty").classList.remove("hidden");
    $("empty").querySelector("h2").textContent = "Nothing here yet";
    $("empty").querySelector("p").textContent = "No results in this run yet — check back as the batch runs.";
    return;
  }
  const firstUnscored = state.results.findIndex((r) => !r.scored_by_me);
  loadImage(firstUnscored >= 0 ? firstUnscored : 0);
}

function showCard(show) {
  $("card").classList.toggle("hidden", !show);
  $("actionbar").classList.toggle("hidden", !show);
  $("empty").classList.toggle("hidden", show);
}

function updateProgress() {
  const done = state.results.filter((r) => r.scored_by_me).length;
  const total = state.results.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("progressBar").querySelector(".bar").style.width = `${pct}%`;
  $("progressText").textContent = `${done} / ${total} scored`;
}

async function loadImage(index) {
  if (index < 0 || index >= state.results.length) return;
  state.index = index;
  const meta = state.results[index];
  const scorer = encodeURIComponent(state.scorer || "");
  const res = await api(`/api/runs/${state.runId}/results/${meta.image_id}?scorer=${scorer}`);
  state.current = res;

  showCard(true);
  $("inputImg").src = res.input_url || "";
  $("promptText").textContent = res.prompt || "(no prompt)";
  renderOutputs(res);

  $("prevBtn").disabled = index === 0;
  const done = meta.scored_by_me ? " ✓" : "";
  $("navInfo").textContent = `Image ${meta.image_id} · ${index + 1} of ${state.results.length}${done}`;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderOutputs(res) {
  const wrap = $("outputs");
  wrap.innerHTML = "";
  (res.outputs || []).forEach((o) => {
    const my = (res.my_scores || {})[o.variant] || {};
    const card = document.createElement("div");
    card.className = "out-card";
    card.dataset.variant = o.variant;
    if (my.value != null) {
      card.classList.add("scored");
      card.dataset.score = my.value;
    }
    if (res.my_best_pick === o.variant) card.classList.add("best");

    const meta = o.status === "ok"
      ? [
          o.model || "?",
          o.thinking_level,
          o.time_taken_ms != null ? `${o.time_taken_ms} ms` : null,
          o.cost_usd != null ? `$${o.cost_usd}` : null,
          o.token_usage && o.token_usage.total != null ? `${o.token_usage.total} tok` : null,
        ].filter(Boolean).join("  ·  ")
      : `ERROR: ${o.error || "failed"}`;

    const scaleBtns = [];
    for (let v = state.range.min; v <= state.range.max; v++) {
      const active = my.value === v;
      const style = active ? `style="background:${scoreColor(v)}"` : "";
      scaleBtns.push(`<button class="sbtn ${active ? "active" : ""}" data-val="${v}" ${style}>${v}</button>`);
    }

    card.innerHTML = `
      <div class="out-top">
        <span><span class="badge">${o.label}</span><span class="variant-tag ${state.reveal ? "" : "hidden"}">${o.variant}</span></span>
        <button class="best-btn ${res.my_best_pick === o.variant ? "active" : ""}">★ Best</button>
      </div>
      <div class="img-wrap">
        ${o.image_url ? `<img class="out-img" src="${o.image_url}" alt="${o.label}" />` : `<div class="out-err">${o.error || "no image"}</div>`}
      </div>
      <div class="meta ${state.reveal ? "show" : ""}">${meta}</div>
      <div class="score-scale">${scaleBtns.join("")}</div>
      <textarea class="comment" placeholder="comment (optional)">${my.comment || ""}</textarea>
    `;

    card.querySelectorAll(".sbtn").forEach((b) => {
      b.addEventListener("click", () => selectScore(card, Number(b.dataset.val)));
    });
    card.querySelector(".best-btn").addEventListener("click", () => toggleBest(card));
    const img = card.querySelector(".out-img");
    if (img) img.addEventListener("click", () => openLightbox(img.src));

    wrap.appendChild(card);
  });

  const refImg = $("inputImg");
  $("card").querySelector("[data-zoom]").onclick = () => openLightbox(refImg.src);
}

function selectScore(card, val) {
  card.dataset.score = val;
  card.classList.add("scored");
  card.querySelectorAll(".sbtn").forEach((b) => {
    const v = Number(b.dataset.val);
    const on = v === val;
    b.classList.toggle("active", on);
    b.style.background = on ? scoreColor(v) : "";
  });
}

function toggleBest(card) {
  const isBest = card.classList.contains("best");
  document.querySelectorAll(".out-card").forEach((c) => {
    c.classList.remove("best");
    c.querySelector(".best-btn").classList.remove("active");
  });
  if (!isBest) {
    card.classList.add("best");
    card.querySelector(".best-btn").classList.add("active");
  }
}

function applyReveal() {
  document.querySelectorAll(".variant-tag").forEach((el) => el.classList.toggle("hidden", !state.reveal));
  document.querySelectorAll(".meta").forEach((el) => el.classList.toggle("show", state.reveal));
}

function openLightbox(src) {
  if (!src) return;
  $("lightboxImg").src = src;
  $("lightbox").classList.remove("hidden");
}

function onKey(e) {
  if ($("lightbox").classList.contains("hidden") === false && e.key === "Escape") {
    $("lightbox").classList.add("hidden");
    return;
  }
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  const typing = tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT";
  if ($("card").classList.contains("hidden")) return;
  if (e.key === "ArrowLeft" && !typing) { e.preventDefault(); loadImage(state.index - 1); }
  else if (e.key === "ArrowRight" && !typing) { e.preventDefault(); loadImage(state.index + 1); }
  else if (e.key === "Enter" && tag !== "TEXTAREA") { e.preventDefault(); saveAndNext(); }
}

async function saveAndNext() {
  if (!state.scorer) { toast("Enter your name first", "err"); return; }

  const scores = {};
  document.querySelectorAll(".out-card").forEach((card) => {
    const variant = card.dataset.variant;
    const comment = card.querySelector(".comment").value;
    if (card.dataset.score) scores[variant] = { value: Number(card.dataset.score), comment };
  });
  const bestCard = document.querySelector(".out-card.best");
  const best_pick = bestCard ? bestCard.dataset.variant : null;

  if (Object.keys(scores).length === 0) { toast("Score at least one output", "err"); return; }

  const meta = state.results[state.index];
  const resp = await api(`/api/runs/${state.runId}/results/${meta.image_id}/score`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scorer: state.scorer, scores, best_pick }),
  }).catch(() => null);

  if (!resp || !resp.ok) { toast("Save failed", "err"); return; }
  toast("Saved ✓");
  state.results[state.index].scored_by_me = true;
  updateProgress();

  const nextUnscored = state.results.findIndex((r, i) => i > state.index && !r.scored_by_me);
  if (nextUnscored >= 0) loadImage(nextUnscored);
  else if (state.index + 1 < state.results.length) loadImage(state.index + 1);
  else toast("All images scored! 🎉");
}

async function showSummary() {
  if (!state.runId) { toast("Pick a run first", "err"); return; }
  const data = await api(`/api/runs/${state.runId}/summary`);
  const entries = Object.entries(data.variants || {});
  const maxAvg = Math.max(1, ...entries.map(([, s]) => s.avg_score || 0));

  const rows = entries
    .sort((a, b) => (b[1].avg_score || 0) - (a[1].avg_score || 0))
    .map(([v, s]) => {
      const avg = s.avg_score;
      const w = avg ? Math.round((avg / maxAvg) * 90) : 0;
      return `<tr>
        <td class="variant">${v}</td>
        <td><div class="bar-cell"><span>${avg ?? "—"}</span><span class="mini-bar" style="width:${w}px"></span></div></td>
        <td>±${s.score_stdev ?? "—"}</td>
        <td>${s.n_scored}</td>
        <td class="win">${s.wins}</td>
        <td>${s.avg_latency_ms ?? "—"}</td>
        <td>${s.p95_latency_ms ?? "—"}</td>
        <td>${s.avg_cost_usd != null ? "$" + s.avg_cost_usd : "—"}</td>
        <td>${s.total_cost_usd != null ? "$" + s.total_cost_usd : "—"}</td>
        <td>${s.n_ok}/${s.n_ok + s.n_err}</td>
      </tr>`;
    })
    .join("");

  $("summaryContent").innerHTML = `
    <p style="color:var(--muted);font-size:13px;margin-top:0">${data.n_images} images · sorted by avg score</p>
    <table>
      <thead><tr>
        <th>model</th><th>avg</th><th>stdev</th><th>n</th><th>wins</th>
        <th>avg ms</th><th>p95 ms</th><th>avg $</th><th>total $</th><th>ok</th>
      </tr></thead>
      <tbody>${rows || '<tr><td colspan="10" style="color:var(--muted)">No scores yet.</td></tr>'}</tbody>
    </table>`;
  $("summaryModal").classList.remove("hidden");
}

init();
