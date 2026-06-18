const $ = (id) => document.getElementById(id);

let mode = "text"; // "text" | "image"
let modelsData = null;

async function loadModels() {
  const res = await fetch("/api/models");
  modelsData = await res.json();

  const status = $("keyStatus");
  if (modelsData.api_key_configured) {
    status.textContent = "API key loaded from .env";
    status.classList.add("ok");
  } else {
    status.textContent = "No API key in .env";
    status.classList.add("bad");
  }
  populateThinkingLevels();
  populateModels();
}

function populateThinkingLevels() {
  const select = $("thinkingLevel");
  select.innerHTML = "";
  (modelsData.image_thinking_levels || []).forEach((lvl) => {
    const opt = document.createElement("option");
    opt.value = lvl;
    opt.textContent = lvl;
    if (lvl === modelsData.default_image_thinking_level) opt.selected = true;
    select.appendChild(opt);
  });
}

function populateModels() {
  const select = $("modelSelect");
  const list = mode === "text" ? modelsData.text_models : modelsData.image_models;
  const def = mode === "text" ? modelsData.default_text_model : modelsData.default_image_model;
  select.innerHTML = "";
  list.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    if (m === def) opt.selected = true;
    select.appendChild(opt);
  });
  $("modelCustom").value = "";
}

function setMode(newMode) {
  mode = newMode;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.mode === newMode);
  });
  $("textOnlyOptions").classList.toggle("hidden", newMode === "image");
  $("imageOnlyOptions").classList.toggle("hidden", newMode !== "image");
  populateModels();
}

function chosenModel() {
  const custom = $("modelCustom").value.trim();
  return custom || $("modelSelect").value;
}

function showImagePreview(file) {
  const preview = $("imagePreview");
  if (!file) {
    preview.classList.add("hidden");
    preview.src = "";
    return;
  }
  preview.src = URL.createObjectURL(file);
  preview.classList.remove("hidden");
}

function resetOutput() {
  $("responseText").textContent = "";
  $("thoughtsText").textContent = "";
  $("thoughtsBox").classList.add("hidden");
  $("imagesOut").innerHTML = "";
  $("meta").textContent = "";
}

function setStatus(kind, text) {
  const el = $("status");
  if (!kind) {
    el.classList.add("hidden");
    return;
  }
  el.className = `status ${kind}`;
  el.textContent = text;
}

async function run() {
  const prompt = $("prompt").value.trim();
  if (!prompt) {
    setStatus("error", "Please enter a prompt.");
    return;
  }

  resetOutput();
  setStatus("loading", "Calling Gemini…");
  $("runBtn").disabled = true;

  const fd = new FormData();
  fd.append("prompt", prompt);
  fd.append("model", chosenModel());

  const imageFile = $("imageInput").files[0];
  if (imageFile) fd.append("image", imageFile);

  const temp = $("temperature").value;

  let endpoint;
  if (mode === "text") {
    endpoint = "/api/generate";
    fd.append("thinking", $("thinking").checked);
    fd.append("include_thoughts", $("includeThoughts").checked);
    const budget = $("thinkingBudget").value;
    if (budget !== "") fd.append("thinking_budget", budget);
    if (temp !== "") fd.append("temperature", temp);
    const sys = $("systemInstruction").value.trim();
    if (sys) fd.append("system_instruction", sys);
  } else {
    endpoint = "/api/image";
    fd.append("thinking_level", $("thinkingLevel").value);
    const imgSize = $("imageSize").value;
    if (imgSize) fd.append("image_size", imgSize);
    const aspect = $("aspectRatio").value;
    if (aspect) fd.append("aspect_ratio", aspect);
    if (temp !== "") fd.append("temperature", temp);
  }

  try {
    const res = await fetch(endpoint, { method: "POST", body: fd });
    const data = await res.json();

    if (!data.ok) {
      setStatus("error", data.error || "Request failed.");
    } else {
      setStatus(null);
    }

    const metaBits = [`model: ${data.model}`, `${data.latency_ms} ms`];
    if (data.usage && Object.keys(data.usage).length) {
      if (data.usage.total_token_count != null) metaBits.push(`${data.usage.total_token_count} tok`);
      if (data.usage.thoughts_token_count != null) metaBits.push(`${data.usage.thoughts_token_count} think-tok`);
    }
    $("meta").textContent = metaBits.join("  ·  ");

    if (data.thoughts) {
      $("thoughtsText").textContent = data.thoughts;
      $("thoughtsBox").classList.remove("hidden");
    }

    if (data.images && data.images.length) {
      const out = $("imagesOut");
      data.images.forEach((img) => {
        const el = document.createElement("img");
        el.src = `data:${img.mime_type};base64,${img.data_b64}`;
        out.appendChild(el);
      });
    }

    if (data.text) $("responseText").textContent = data.text;
  } catch (err) {
    setStatus("error", `Network error: ${err.message}`);
  } finally {
    $("runBtn").disabled = false;
  }
}

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => setMode(t.dataset.mode));
});
$("imageInput").addEventListener("change", (e) => showImagePreview(e.target.files[0]));
$("runBtn").addEventListener("click", run);

loadModels();
