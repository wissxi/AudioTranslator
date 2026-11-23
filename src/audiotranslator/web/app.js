/* AudioTranslator — interface logic.
   Talks to Python through window.pywebview.api; Python pushes events to AT.receive(). */
(() => {
  "use strict";

  // ------------------------------------------------------------ utilities
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  let dict = window.I18N.en;
  let plural = new Intl.PluralRules("en");

  function t(key, vars = {}) {
    let entry = dict[key] ?? window.I18N.en[key] ?? key;
    if (typeof entry === "object") {
      entry = entry[plural.select(vars.count ?? 0)] ?? entry.other;
    }
    return entry.replace(/\{(\w+)\}/g, (_, name) => (vars[name] ?? `{${name}}`));
  }

  function fmtDuration(sec) {
    if (sec == null || !isFinite(sec)) return "";
    const s = Math.round(sec);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
  }

  function fmtBytes(bytes) {
    if (bytes == null) return "";
    const units = [["gb", 1 << 30], ["mb", 1 << 20], ["kb", 1 << 10]];
    for (const [unit, size] of units) {
      if (bytes >= size) {
        const value = bytes / size;
        return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${t("unit." + unit)}`;
      }
    }
    return `${bytes} ${t("unit.b")}`;
  }

  function fmtEta(sec) {
    if (sec < 60) return t("unit.lessMinute");
    const min = Math.round(sec / 60);
    if (min < 60) return `${min} ${t("unit.min")}`;
    return `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")}`;
  }

  // -------------------------------------------------------------- state
  const state = {
    info: null,
    settings: null,
    queue: [],
    selectedId: null,
    follow: true, // keep the processed file selected while a job runs
    running: false,
    job: null,
    settingsOpen: false,
  };
  let api = null;
  const colors = {};

  const byId = (id) => state.queue.find((item) => item.id === id);
  const selected = () => byId(state.selectedId);
  const languages = () => state.info?.languages ?? [];
  const langName = (code) => {
    const lang = languages().find((l) => l.code === code);
    if (!lang) return (code || "").toUpperCase();
    return state.settings.ui_language === "ru" ? lang.ru : lang.en;
  };
  const modelInfo = (name) => state.info?.models.find((m) => m.name === name);

  function newItem(info) {
    return {
      ...info,
      status: "queued",
      stage: null,
      progress: 0,
      recognizedTo: 0,
      waveform: null,
      segments: [],
      language: null,
      target: null,
      plannedTarget: null,
      outputs: [],
      error: null,
      notes: [],
      translationCode: null,
    };
  }

  function resetItem(item) {
    Object.assign(item, {
      status: "queued",
      stage: null,
      progress: 0,
      recognizedTo: 0,
      segments: [],
      language: null,
      target: null,
      outputs: [],
      error: null,
      notes: [],
      translationCode: null,
    });
  }

  // ---------------------------------------------------------------- boot
  function connect() {
    if (/[?&]demo\b/.test(location.search)) {
      const script = document.createElement("script");
      script.src = "mock.js";
      script.onload = () => {
        api = new window.MockAPI(window.AT);
        start();
      };
      document.body.appendChild(script);
      return;
    }
    if (window.pywebview?.api?.init) {
      api = window.pywebview.api;
      start();
    } else {
      window.addEventListener(
        "pywebviewready",
        () => {
          api = window.pywebview.api;
          start();
        },
        { once: true },
      );
    }
  }

  async function start() {
    const info = await api.init();
    state.info = info;
    state.settings = info.settings;
    applyLanguage();
    applyTheme();
    drawEmptyWave();
    bindStatic();
    renderAll();
    if (api.ready) api.ready();
  }

  // ------------------------------------------------------- theme & i18n
  function applyLanguage() {
    const ui = state.settings.ui_language === "ru" ? "ru" : "en";
    dict = window.I18N[ui];
    plural = new Intl.PluralRules(ui);
    document.documentElement.lang = ui;
    $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    $$("[data-i18n-title]").forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
      el.setAttribute("aria-label", el.title);
    });
  }

  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    const pref = state.settings.theme;
    const resolved = pref === "system" ? (darkQuery.matches ? "dark" : "light") : pref;
    document.documentElement.dataset.theme = resolved;
    const css = getComputedStyle(document.documentElement);
    for (const name of ["signal", "wave-idle", "text", "faint", "line-strong", "muted"]) {
      colors[name] = css.getPropertyValue(`--${name}`).trim();
    }
    api?.set_theme?.(resolved === "dark");
    drawWave();
  }
  darkQuery.addEventListener("change", () => state.settings?.theme === "system" && applyTheme());

  // -------------------------------------------------------------- render
  function renderAll() {
    renderView();
    renderQueue();
    renderStage();
    renderDeck();
    if (state.settingsOpen) renderSettings();
  }

  function renderView() {
    const app = $("#app");
    app.dataset.view = state.queue.length ? "files" : "empty";
    app.toggleAttribute("data-running", state.running);
    $("#empty").hidden = state.queue.length > 0;
    $("#file-view").hidden = !selected();
  }

  function statusText(item) {
    if (item.status === "active") return t("status." + (item.stage || "decoding"));
    return t("status." + item.status);
  }

  function renderQueue() {
    const list = $("#queue-list");
    list.innerHTML = state.queue
      .map((item) => {
        const meta = [fmtDuration(item.duration)];
        if (item.status !== "queued") meta.unshift(statusText(item));
        let side = "";
        if (item.status === "done") side = icon("circle-check", "q-state q-state-done");
        else if (item.status === "error") side = icon("circle-alert", "q-state q-state-error");
        else if (item.status === "active") side = icon("loader-circle", "q-state spin");
        return `
          <li class="q-item" role="option" data-id="${esc(item.id)}" data-status="${item.status}"
              aria-selected="${item.id === state.selectedId}" title="${esc(item.path)}">
            ${icon(item.kind === "video" ? "file-video" : "file-audio", "q-kind")}
            <span class="q-name">${esc(item.name)}</span>
            <span class="q-side">${side}
              <button class="icon-btn q-remove" type="button" data-remove="${esc(item.id)}"
                      title="${esc(t("queue.remove"))}" aria-label="${esc(t("queue.remove"))}">${icon("x", "i-sm")}</button>
            </span>
            <span class="q-meta num">${esc(meta.filter(Boolean).join(", "))}</span>
            ${item.status === "active" ? `<span class="q-bar"><i style="--p:${item.progress}"></i></span>` : ""}
          </li>`;
      })
      .join("");

    const total = state.queue.reduce((sum, item) => sum + (item.duration || 0), 0);
    const parts = [t("queue.files", { count: state.queue.length })];
    if (total) parts.push(fmtDuration(total));
    $("#queue-summary").textContent = parts.join(", ");
    $("#btn-clear").disabled = state.running || !state.queue.length;
    $("#btn-add-files").disabled = false;
  }

  function updateQueueItem(item) {
    const li = $(`.q-item[data-id="${CSS.escape(item.id)}"]`);
    if (!li) return renderQueue();
    if (li.dataset.status !== item.status) return renderQueue();
    const meta = $(".q-meta", li);
    meta.textContent = [statusText(item), fmtDuration(item.duration)].filter(Boolean).join(", ");
    const bar = $(".q-bar > i", li);
    if (bar) bar.style.setProperty("--p", item.progress);
  }

  // ---- stage
  function renderStage() {
    const item = selected();
    $("#file-view").hidden = !item;
    if (!item) return;

    $("#fv-name").textContent = item.name;
    $("#fv-name").title = item.path;
    renderMeta(item);
    renderActions(item);
    renderNotice(item);
    renderLanes(item);
    renderOutputs(item);
    $("#wave-end").textContent = fmtDuration(item.duration);
    drawWave();
  }

  function renderMeta(item) {
    const parts = [];
    const cls = item.status === "active" ? "state-active" : item.status === "error" ? "state-error" : item.status === "done" ? "state-done" : "";
    parts.push(`<span class="${cls}">${esc(statusText(item))}${item.status === "active" ? ` ${Math.round(item.progress * 100)}%` : ""}</span>`);
    if (item.duration) parts.push(`<span>${esc(fmtDuration(item.duration))}</span>`);
    if (item.size) parts.push(`<span>${esc(fmtBytes(item.size))}</span>`);
    if (item.language) {
      let lang = langName(item.language);
      if (item.target && translated(item)) lang += ` → ${langName(item.target)}`;
      parts.push(`<span>${esc(lang)}</span>`);
    }
    $("#fv-meta").innerHTML = parts.join("");
  }

  function renderActions(item) {
    const hasText = item.segments.length > 0;
    const hasTr = translated(item);
    const buttons = [];
    if (hasText) buttons.push(["copy-orig", "copy", t("file.copyOrig")]);
    if (hasTr) buttons.push(["copy-tr", "languages", t("file.copyTr")]);
    if (item.outputs.length) buttons.push(["reveal", "folder-open", t("file.reveal")]);
    $("#fv-actions").innerHTML = buttons
      .map(([action, ic, label]) => `<button class="icon-btn" type="button" data-action="${action}" title="${esc(label)}" aria-label="${esc(label)}">${icon(ic)}</button>`)
      .join("");
  }

  function renderNotice(item) {
    const box = $("#fv-notice");
    let tone = "info";
    let text = "";
    if (item.status === "error" && item.error) {
      tone = "error";
      const key = "err." + item.error.code;
      text = dict[key] ? t(key, { message: item.error.message }) : t("err.unexpected", { message: item.error.message });
    } else if (item.notes.length) {
      text = item.notes.join(" ");
    } else if (item.status === "done" && !item.segments.length) {
      text = t("file.noSpeech");
    }
    box.hidden = !text;
    if (text) {
      box.dataset.tone = tone;
      box.innerHTML = `${icon(tone === "error" ? "circle-alert" : "info")}<span>${esc(text)}</span>`;
    }
  }

  const translated = (item) => item.segments.some((seg) => seg.translation);

  function laneTarget(item) {
    if (item.status === "done") return item.target && translated(item) ? item.target : null;
    return item.plannedTarget && item.plannedTarget !== item.language ? item.plannedTarget : null;
  }

  function renderLanes(item) {
    const lanes = $("#lanes");
    const target = laneTarget(item);
    lanes.toggleAttribute("data-single", !target);
    const origLabel = item.language ? `${esc(langName(item.language))}<span class="lang-code">${esc(item.language.toUpperCase())}</span>` : esc(t("lane.original"));
    const waiting = target && item.status !== "done" && !translated(item);
    const trLabel = target
      ? `${esc(langName(target))}<span class="lang-code">${esc(target.toUpperCase())}</span>${waiting ? `<span class="lane-hint">${esc(t("lane.afterRecognition"))}</span>` : ""}`
      : "";
    $("#lanes-head").innerHTML = `<span></span><span>${origLabel}</span>${target ? `<span>${trLabel}</span>` : ""}`;

    const body = $("#lanes-body");
    if (!item.segments.length) {
      body.innerHTML = item.status === "done" || item.status === "error" ? "" : `<p class="lanes-empty">${esc(t("file.waiting"))}</p>`;
      return;
    }
    body.innerHTML = item.segments.map((seg, i) => laneRow(item, seg, i, target)).join("");
    if (item.status === "active") markLive(body);
  }

  function laneRow(item, seg, index, target) {
    const tr = target ? `<div class="lane-tr">${esc(seg.translation || "")}</div>` : "";
    return `<div class="lane-row" data-index="${index}">
      <div class="lane-time">${esc(fmtDuration(seg.start))}</div>
      <div class="lane-orig">${esc(seg.text)}</div>${tr}
    </div>`;
  }

  function markLive(body) {
    $$(".lane-row[data-live]", body).forEach((row) => row.removeAttribute("data-live"));
    body.lastElementChild?.setAttribute("data-live", "");
  }

  function appendSegment(item, seg) {
    const body = $("#lanes-body");
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    if (item.segments.length === 1) {
      renderLanes(item);
    } else {
      body.insertAdjacentHTML("beforeend", laneRow(item, seg, item.segments.length - 1, laneTarget(item)));
      markLive(body);
    }
    if (nearBottom) body.scrollTop = body.scrollHeight;
    renderActions(item);
  }

  function renderOutputs(item) {
    const box = $("#fv-outputs");
    box.hidden = !item.outputs.length;
    if (!item.outputs.length) return;
    box.innerHTML =
      `<span class="outputs-label">${esc(t("file.outputs"))}</span>` +
      item.outputs
        .map((path) => {
          const name = path.split(/[\\/]/).pop();
          return `<button class="chip" type="button" data-open="${esc(path)}" title="${esc(path)}">${icon("file-text", "i-sm")}${esc(name)}</button>`;
        })
        .join("");
  }

  // ---- waveform
  function resample(peaks, count) {
    if (!peaks?.length) return null;
    const out = new Array(count);
    for (let i = 0; i < count; i++) {
      const a = Math.floor((i / count) * peaks.length);
      const b = Math.max(a + 1, Math.floor(((i + 1) / count) * peaks.length));
      let max = 0;
      for (let j = a; j < b; j++) max = Math.max(max, peaks[j]);
      out[i] = max;
    }
    return out;
  }

  let hotRange = null;
  function drawWave() {
    const item = selected();
    const canvas = $("#wave");
    if (!item || !canvas || $("#file-view").hidden) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;
    const slot = 4;
    const bar = 2.4;
    const count = Math.floor(W / slot);
    const peaks = resample(item.waveform, count);
    const duration = item.duration || 1;

    const active = item.status === "active";
    const fraction = active ? clamp(item.recognizedTo / duration, 0, 1) : 0;
    const progressX = fraction * W;
    const base = item.status === "done" ? colors.muted : colors["wave-idle"];

    for (let i = 0; i < count; i++) {
      const x = i * slot;
      const amp = peaks ? Math.max(0.045, peaks[i]) : 0.045;
      const h = Math.max(2, amp * (H - 6));
      const y = (H - h) / 2;
      let color = x < progressX ? colors.signal : base;
      let alpha = item.status === "done" ? 0.55 : 1;
      if (hotRange) {
        const t0 = (x / W) * duration;
        if (t0 >= hotRange[0] - (duration / count) && t0 <= hotRange[1]) {
          color = colors.signal;
          alpha = 1;
        }
      }
      ctx.globalAlpha = alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.roundRect(x, y, bar, h, bar / 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    if (active && fraction > 0 && fraction < 1) {
      ctx.fillStyle = colors.signal;
      ctx.fillRect(Math.round(progressX), 0, 2, H);
    }
  }

  function drawEmptyWave() {
    const svg = $("#empty-wave");
    const count = 96;
    const width = 560;
    const slot = width / count;
    let bars = "";
    for (let i = 0; i < count; i++) {
      const env = 0.35 + 0.65 * Math.abs(Math.sin(i * 0.11) * Math.cos(i * 0.037));
      const jitter = 0.55 + 0.45 * Math.abs(Math.sin(i * 1.7 + 0.3));
      const h = Math.max(3, 64 * env * jitter);
      bars += `<rect x="${(i * slot).toFixed(1)}" y="${((72 - h) / 2).toFixed(1)}" width="${(slot * 0.55).toFixed(1)}" height="${h.toFixed(1)}" rx="1.6"/>`;
    }
    svg.setAttribute("viewBox", `0 0 ${width} 72`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = `<g fill="currentColor">${bars}</g>`;
  }

  // ---- deck
  function selectButton(label, value) {
    return `<span class="sb-text"><span class="sb-label">${esc(label)}</span><span class="sb-value">${esc(value)}</span></span>${icon("chevron-down", "i-sm chev")}`;
  }

  function renderDeck() {
    const s = state.settings;
    const running = state.running;
    $("#sel-source").innerHTML = selectButton(t("deck.from"), s.source_language ? langName(s.source_language) : t("deck.auto"));
    $("#sel-target").innerHTML = selectButton(t("deck.to"), s.target_language ? langName(s.target_language) : t("deck.noTranslation"));
    $("#sel-model").innerHTML = selectButton(t("deck.model"), s.model);
    for (const id of ["#sel-source", "#sel-target", "#sel-model", "#deck-output"]) $(id).disabled = running;

    $("#deck-formats").innerHTML = ["txt", "srt", "vtt", "json"]
      .map((fmt) => `<button class="fmt-toggle" type="button" data-fmt="${fmt}" aria-pressed="${s.formats.includes(fmt)}" title="${esc(t("set.fmt." + fmt))}" ${running ? "disabled" : ""}>${fmt.toUpperCase()}</button>`)
      .join("");

    const folder = s.output_dir ? s.output_dir.split(/[\\/]/).filter(Boolean).pop() : "";
    $("#deck-output-text").textContent = folder ? t("deck.outputIn", { folder }) : t("deck.outputBeside");
    $("#deck-output").title = s.output_dir || t("deck.outputBeside");

    const btn = $("#btn-start");
    if (running) {
      btn.className = "btn btn-stop";
      btn.innerHTML = `${icon("square")}<span>${esc(state.job?.stopping ? t("deck.stopping") : t("deck.stop"))}</span>`;
      btn.disabled = !!state.job?.stopping;
    } else {
      btn.className = "btn btn-primary";
      const label = s.target_language ? t("deck.startTranslate") : t("deck.startTranscribe");
      btn.innerHTML = `${icon("play")}<span>${esc(label)}</span>`;
      btn.disabled = !state.queue.length;
    }
    renderDeckStatus();
  }

  function jobProgress() {
    const job = state.job;
    if (!job) return { fraction: 0, eta: null };
    const items = job.ids.map(byId).filter(Boolean);
    const weight = (item) => item.duration || 60;
    const total = items.reduce((sum, item) => sum + weight(item), 0) || 1;
    const done = items.reduce((sum, item) => {
      if (["done", "error"].includes(item.status)) return sum + weight(item);
      if (item.status === "active") return sum + weight(item) * item.progress;
      return sum;
    }, 0);
    const fraction = clamp(done / total, 0, 1);
    let eta = null;
    if (job.workStartedAt && fraction > 0.02) {
      const elapsed = (Date.now() - job.workStartedAt) / 1000;
      if (elapsed > 4) eta = (elapsed / fraction) * (1 - fraction);
    }
    return { fraction, eta };
  }

  function renderDeckStatus() {
    const job = state.job;
    if (!state.running || !job) return;
    const { fraction, eta } = jobProgress();
    $("#deck-bar").style.setProperty("--p", fraction);
    let main = t("deck.preparing");
    let sub = "";
    if (job.phase === "model") {
      const info = modelInfo(job.model?.name);
      if (job.model?.downloading && info) {
        const totalBytes = info.size_mb * 1048576;
        main = t("deck.downloading", { model: job.model.name, done: fmtBytes((job.model.progress || 0) * totalBytes), total: fmtBytes(totalBytes) });
        $("#deck-bar").style.setProperty("--p", job.model.progress || 0);
      } else if (job.model) {
        main = t("deck.loadingModel", { model: job.model.name });
      }
    } else if (job.currentId) {
      const item = byId(job.currentId);
      main = item?.name ?? "";
      const bits = [t("deck.fileOf", { index: job.index + 1, total: job.ids.length })];
      if (job.device) bits.push(`${job.modelName} ${t("deck.device." + job.device)}`);
      if (eta != null) bits.push(t("deck.eta", { eta: fmtEta(eta) }));
      sub = bits.join(", ");
    }
    $("#deck-status-main").textContent = main;
    $("#deck-status-sub").textContent = sub;
  }

  // -------------------------------------------------------------- popover
  let popover = null;
  function closePopover() {
    if (!popover) return;
    popover.anchor.setAttribute("aria-expanded", "false");
    popover.el.remove();
    document.removeEventListener("mousedown", popover.outside, true);
    popover = null;
  }

  function openSelect(anchor, { options, value, search = false, onPick, width = 280 }) {
    if (popover?.anchor === anchor) return closePopover();
    closePopover();
    const el = document.createElement("div");
    el.className = "popover";
    el.style.width = `${width}px`;
    el.innerHTML = `${search ? `<div class="pop-search">${icon("search", "i-sm")}<input type="text" placeholder="${esc(t("deck.searchLang"))}" aria-label="${esc(t("deck.searchLang"))}"></div>` : ""}<ul class="pop-list" role="listbox"></ul>`;
    document.body.appendChild(el);

    const list = $(".pop-list", el);
    const input = $("input", el);
    let visible = [];
    let active = 0;

    function draw() {
      const q = (input?.value || "").trim().toLowerCase();
      visible = options.filter((o) => o.sep ? !q : !q || o.search.includes(q));
      if (!visible.some((o) => !o.sep)) {
        list.innerHTML = `<li class="pop-empty">${esc(t("deck.noMatch"))}</li>`;
        return;
      }
      active = clamp(active, 0, visible.length - 1);
      if (visible[active]?.sep) active = visible.findIndex((o) => !o.sep);
      list.innerHTML = visible
        .map((o, i) =>
          o.sep
            ? `<li class="pop-sep" role="separator"></li>`
            : `<li class="pop-opt" role="option" data-i="${i}" aria-selected="${o.value === value}" ${i === active ? "data-active" : ""}>
                ${icon("check", "i-sm po-check")}
                <span class="po-text"><span>${esc(o.label)}</span>${o.hint ? `<span class="po-hint">${esc(o.hint)}</span>` : ""}</span>
                ${o.side ? `<span class="po-side">${o.side}</span>` : ""}
              </li>`,
        )
        .join("");
    }

    function move(delta) {
      let i = active;
      do {
        i = clamp(i + delta, 0, visible.length - 1);
      } while (visible[i]?.sep && i > 0 && i < visible.length - 1);
      active = i;
      draw();
      $(".pop-opt[data-active]", list)?.scrollIntoView({ block: "nearest" });
    }

    function pick(i) {
      const opt = visible[i];
      if (!opt || opt.sep) return;
      closePopover();
      anchor.focus();
      onPick(opt.value);
    }

    list.addEventListener("mousedown", (e) => {
      const li = e.target.closest(".pop-opt");
      if (li) {
        e.preventDefault();
        pick(Number(li.dataset.i));
      }
    });
    list.addEventListener("mousemove", (e) => {
      const li = e.target.closest(".pop-opt");
      if (li && Number(li.dataset.i) !== active) {
        active = Number(li.dataset.i);
        $$(".pop-opt", list).forEach((x) => x.toggleAttribute("data-active", x === li));
      }
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") (e.preventDefault(), move(1));
      else if (e.key === "ArrowUp") (e.preventDefault(), move(-1));
      else if (e.key === "Enter") (e.preventDefault(), pick(active));
      else if (e.key === "Escape") (e.preventDefault(), closePopover(), anchor.focus());
    });
    input?.addEventListener("input", () => {
      active = 0;
      draw();
    });

    active = Math.max(0, options.findIndex((o) => o.value === value));
    draw();

    // position above the anchor (the deck lives at the bottom of the window)
    const r = anchor.getBoundingClientRect();
    const left = clamp(r.left, 8, window.innerWidth - width - 8);
    el.style.left = `${left}px`;
    el.style.bottom = `${window.innerHeight - r.top + 8}px`;
    el.style.maxHeight = `${Math.min(440, r.top - 24)}px`;

    const outside = (e) => {
      if (!el.contains(e.target) && !anchor.contains(e.target)) closePopover();
    };
    document.addEventListener("mousedown", outside, true);
    anchor.setAttribute("aria-expanded", "true");
    popover = { el, anchor, outside };
    (input || el).focus?.();
    if (!input) {
      el.tabIndex = -1;
      el.focus();
    }
    $(".pop-opt[aria-selected=true]", list)?.scrollIntoView({ block: "center" });
  }

  function languageOptions(first) {
    const ui = state.settings.ui_language;
    const pinned = ["en", "ru", "uk", "de", "fr", "es", "it", "zh", "ja", "ko"];
    const name = (l) => (ui === "ru" ? l.ru : l.en);
    const all = languages();
    const top = pinned.map((code) => all.find((l) => l.code === code)).filter(Boolean);
    const rest = all.filter((l) => !pinned.includes(l.code)).sort((a, b) => name(a).localeCompare(name(b), ui));
    const toOpt = (l) => ({
      value: l.code,
      label: name(l),
      hint: l.native !== name(l) ? l.native : "",
      side: esc(l.code.toUpperCase()),
      search: `${l.en} ${l.ru} ${l.native} ${l.code}`.toLowerCase(),
    });
    return [first, { sep: true }, ...top.map(toOpt), { sep: true }, ...rest.map(toOpt)];
  }

  function modelOptions() {
    return state.info.models.map((m) => ({
      value: m.name,
      label: m.name,
      hint: t("model." + m.name),
      side: m.downloaded ? `<span style="color:var(--ok)">${esc(t("deck.downloaded"))}</span>` : esc(t("deck.notDownloaded", { size: fmtBytes(m.size_mb * 1048576) })),
      search: m.name,
    }));
  }

  // -------------------------------------------------------------- settings
  async function saveSettings(patch) {
    Object.assign(state.settings, patch);
    renderDeck();
    const saved = await api.save_settings(patch);
    if (saved) state.settings = saved;
    if ("ui_language" in patch) {
      applyLanguage();
      renderAll();
    } else if ("theme" in patch) {
      applyTheme();
    } else {
      renderDeck();
    }
    if (state.settingsOpen) renderSettings();
  }

  function seg(name, current, values) {
    return `<div class="seg" role="radiogroup">${values
      .map(([value, label]) => `<button type="button" role="radio" aria-checked="${value === current}" data-set="${name}" data-value="${esc(value)}">${esc(label)}</button>`)
      .join("")}</div>`;
  }

  function switchRow(name, title, hint) {
    const on = !!state.settings[name];
    return `<div class="switch-row" data-toggle="${name}">
      <span class="sw-text"><span>${esc(title)}</span>${hint ? `<span class="hint">${esc(hint)}</span>` : ""}</span>
      <button type="button" class="switch" role="switch" aria-checked="${on}" aria-label="${esc(title)}"></button>
    </div>`;
  }

  function renderSettings() {
    const root = $("#settings-root");
    if (!state.settingsOpen) {
      root.innerHTML = "";
      return;
    }
    const s = state.settings;
    const info = state.info;
    const running = state.running;
    const models = info.models
      .map(
        (m) => `<button type="button" class="model-opt" role="radio" aria-checked="${m.name === s.model}" data-set="model" data-value="${m.name}" ${running ? "disabled" : ""}>
          <span class="radio-dot"></span>
          <span class="model-name">${esc(m.name)}</span>
          <span class="model-size num">${m.downloaded ? `<span class="got">${esc(t("deck.downloaded"))}</span>` : `~${esc(fmtBytes(m.size_mb * 1048576))}`}</span>
          <span class="model-desc">${esc(t("model." + m.name))}</span>
        </button>`,
      )
      .join("");

    const formats = ["txt", "srt", "vtt", "json"]
      .map((fmt) => `<button class="fmt-toggle" type="button" data-fmt="${fmt}" aria-pressed="${s.formats.includes(fmt)}" title="${esc(t("set.fmt." + fmt))}">${fmt.toUpperCase()}</button>`)
      .join("");

    root.innerHTML = `
      <div class="scrim" data-close></div>
      <aside class="sheet" role="dialog" aria-modal="true" aria-labelledby="set-title">
        <div class="sheet-head">
          <h2 id="set-title">${esc(t("set.title"))}</h2>
          <button class="icon-btn" type="button" data-close title="${esc(t("set.close"))}" aria-label="${esc(t("set.close"))}">${icon("x")}</button>
        </div>
        <div class="sheet-body">
          <section class="set-group">
            <h3>${esc(t("set.recognition"))}</h3>
            <div class="field">
              <span class="field-label">${esc(t("set.model"))}</span>
              <div class="model-list" role="radiogroup">${models}</div>
              <p class="hint">${esc(t("set.modelHint"))}</p>
            </div>
            <div class="field">
              <span class="field-label">${esc(t("set.device"))}</span>
              ${seg("device", s.device, [["auto", t("set.device.auto")], ["cpu", t("set.device.cpu")], ["cuda", t("set.device.cuda")]])}
              <p class="hint">${esc(info.gpu ? t("set.gpuFound") : t("set.gpuMissing"))}</p>
            </div>
            ${switchRow("vad", t("set.vad"), t("set.vadHint"))}
          </section>

          <section class="set-group">
            <h3>${esc(t("set.translation"))}</h3>
            <div class="field">
              <span class="field-label">${esc(t("set.provider"))}</span>
              ${seg("provider", s.provider, [["google", t("set.provider.google")], ["deepl", t("set.provider.deepl")], ["mymemory", t("set.provider.mymemory")]])}
              <p class="hint">${esc(t("set.providerHint." + s.provider))}</p>
            </div>
            ${s.provider === "deepl" ? `
              <div class="field">
                <label class="field-label" for="deepl-key">${esc(t("set.deeplKey"))}</label>
                <input class="text-input" id="deepl-key" type="password" autocomplete="off" spellcheck="false" value="${esc(s.deepl_key)}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx">
                <p class="hint">${esc(t("set.deeplKeyHint"))}</p>
              </div>` : ""}
            ${switchRow("fallback", t("set.fallback"), t("set.fallbackHint"))}
          </section>

          <section class="set-group">
            <h3>${esc(t("set.output"))}</h3>
            <div class="field">
              <span class="field-label">${esc(t("set.outputFolder"))}</span>
              ${seg("output_mode", s.output_dir ? "custom" : "beside", [["beside", t("set.outputBeside")], ["custom", t("set.outputCustom")]])}
              ${s.output_dir ? `<div class="path-row"><span class="path-box" title="${esc(s.output_dir)}">${esc(s.output_dir)}</span><button class="btn" type="button" data-action="pick-output">${esc(t("set.choose"))}</button></div>` : ""}
            </div>
            <div class="field">
              <span class="field-label">${esc(t("set.formats"))}</span>
              <div class="deck-formats" style="display:flex">${formats}</div>
            </div>
            ${switchRow("report", t("set.report"), t("set.reportHint"))}
            ${switchRow("include_original", t("set.original"), t("set.originalHint"))}
            ${switchRow("recursive", t("set.recursive"), t("set.recursiveHint"))}
          </section>

          <section class="set-group">
            <h3>${esc(t("set.interface"))}</h3>
            <div class="field">
              <span class="field-label">${esc(t("set.uiLanguage"))}</span>
              ${seg("ui_language", s.ui_language, [["ru", "Русский"], ["en", "English"]])}
            </div>
            <div class="field">
              <span class="field-label">${esc(t("set.theme"))}</span>
              ${seg("theme", s.theme, [["system", t("set.theme.system")], ["light", t("set.theme.light")], ["dark", t("set.theme.dark")]])}
            </div>
          </section>

          <section class="set-group">
            <h3>${esc(t("set.about"))}</h3>
            <div class="about">
              <span>AudioTranslator ${esc(t("set.version", { version: info.version }))}</span>
              <div class="about-links">
                <button class="chip" type="button" data-action="github">${icon("external-link", "i-sm")}${esc(t("set.github"))}</button>
                <button class="chip" type="button" data-action="models-folder">${icon("folder", "i-sm")}${esc(t("set.modelsFolder"))}</button>
              </div>
            </div>
          </section>
        </div>
      </aside>`;

    const key = $("#deepl-key", root);
    if (key) {
      let timer;
      key.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => saveSettings({ deepl_key: key.value.trim() }), 400);
      });
    }
  }

  function openSettings() {
    state.settingsOpen = true;
    closePopover();
    renderSettings();
    $("#settings-root .sheet .icon-btn")?.focus();
  }

  function closeSettings() {
    state.settingsOpen = false;
    renderSettings();
    $("#btn-settings").focus();
  }

  async function handleSettingsClick(e) {
    const target = e.target;
    if (target.closest("[data-close]")) return closeSettings();
    const toggle = target.closest("[data-toggle]");
    if (toggle) return saveSettings({ [toggle.dataset.toggle]: !state.settings[toggle.dataset.toggle] });
    const fmt = target.closest("[data-fmt]");
    if (fmt) return toggleFormat(fmt.dataset.fmt);
    const set = target.closest("[data-set]");
    if (set && !set.disabled) {
      const { set: name, value } = set.dataset;
      if (name === "output_mode") {
        if (value === "beside") return saveSettings({ output_dir: "" });
        return pickOutputDir();
      }
      return saveSettings({ [name]: value });
    }
    const action = target.closest("[data-action]")?.dataset.action;
    if (action === "pick-output") return pickOutputDir();
    if (action === "github") return api.open_url(state.info.repo_url);
    if (action === "models-folder") return api.open_path(state.info.models_dir);
  }

  async function pickOutputDir() {
    const dir = await api.pick_output_dir();
    if (dir) saveSettings({ output_dir: dir });
  }

  function toggleFormat(fmt) {
    const formats = state.settings.formats.includes(fmt)
      ? state.settings.formats.filter((f) => f !== fmt)
      : [...state.settings.formats, fmt];
    saveSettings({ formats });
  }

  // ----------------------------------------------------------- queue ops
  function addFiles(files, { notify = true } = {}) {
    let added = 0;
    for (const info of files || []) {
      if (byId(info.id)) continue;
      state.queue.push(newItem(info));
      added++;
    }
    if (!state.selectedId && state.queue.length) state.selectedId = state.queue[0].id;
    if (notify && files && !files.length) toast(t("toast.noMedia"), "info");
    renderAll();
    return added;
  }

  async function chooseFiles() {
    addFiles(await api.pick_files(), { notify: false });
  }

  async function chooseFolder() {
    const files = await api.pick_folder();
    if (files) addFiles(files);
  }

  function removeItem(id) {
    if (state.running) return;
    const index = state.queue.findIndex((item) => item.id === id);
    if (index < 0) return;
    state.queue.splice(index, 1);
    if (state.selectedId === id) state.selectedId = state.queue[Math.min(index, state.queue.length - 1)]?.id ?? null;
    renderAll();
  }

  function selectItem(id) {
    state.selectedId = id;
    if (state.running) state.follow = id === state.job?.currentId;
    hotRange = null;
    renderQueue();
    renderStage();
  }

  async function startJob() {
    if (state.running) {
      if (state.job) state.job.stopping = true;
      renderDeck();
      await api.cancel();
      return;
    }
    let items = state.queue.filter((item) => item.status !== "done");
    if (!items.length) items = state.queue.slice();
    if (!items.length) return;
    for (const item of items) {
      resetItem(item);
      item.plannedTarget = state.settings.target_language || null;
    }
    state.running = true;
    state.follow = true;
    state.job = { ids: items.map((i) => i.id), phase: "model", index: 0, stopping: false, startedAt: Date.now() };
    renderAll();
    const result = await api.start(items.map(({ id, path }) => ({ id, path })));
    if (result && result.ok === false) {
      state.running = false;
      state.job = null;
      renderAll();
    }
  }

  // ------------------------------------------------------- backend events
  const handlers = {
    files_added(e) {
      const added = addFiles(e.files, { notify: !e.quiet });
      if (added && !e.quiet) toast(t("toast.added", { count: added }), "ok");
    },
    job_started(e) {
      // Normally set by startJob(); this covers jobs started elsewhere (e.g. demo snapshots).
      if (state.running) return;
      state.running = true;
      state.follow = true;
      state.job = { ids: e.ids || [], phase: "model", index: 0, stopping: false, startedAt: Date.now() };
      for (const item of state.job.ids.map(byId)) {
        if (item) item.plannedTarget = state.settings.target_language || null;
      }
      renderAll();
    },
    model_loading(e) {
      state.job.phase = "model";
      state.job.model = { name: e.model, downloading: e.downloading, progress: 0 };
      renderDeckStatus();
    },
    model_download(e) {
      if (state.job?.model) state.job.model.progress = e.progress;
      renderDeckStatus();
    },
    model_ready(e) {
      Object.assign(state.job, { phase: "files", device: e.device, modelName: e.model, workStartedAt: Date.now() });
      const m = modelInfo(e.model);
      if (m) m.downloaded = true;
      renderDeckStatus();
    },
    file_started(e) {
      const item = byId(e.id);
      if (!item) return;
      Object.assign(item, { status: "active", stage: "decoding", progress: 0 });
      state.job.currentId = e.id;
      state.job.index = e.index;
      if (state.follow) state.selectedId = e.id;
      renderQueue();
      if (state.selectedId === e.id) renderStage();
      renderDeckStatus();
    },
    file_audio(e) {
      const item = byId(e.id);
      if (!item) return;
      item.waveform = e.waveform;
      item.duration = e.duration;
      if (state.selectedId === e.id) renderStage();
    },
    file_progress(e) {
      const item = byId(e.id);
      if (!item) return;
      const stageChanged = item.stage !== e.stage;
      item.stage = e.stage;
      item.progress = e.progress;
      updateQueueItem(item);
      if (state.selectedId === e.id) {
        renderMeta(item);
        if (stageChanged) drawWave();
      }
      renderDeckStatus();
    },
    segment(e) {
      const item = byId(e.id);
      if (!item) return;
      const seg = { start: e.start, end: e.end, text: e.text, translation: "" };
      item.segments.push(seg);
      item.recognizedTo = e.end;
      if (state.selectedId === e.id) {
        appendSegment(item, seg);
        drawWave();
      }
    },
    file_language(e) {
      const item = byId(e.id);
      if (!item) return;
      item.language = e.language;
      if (state.selectedId === e.id) {
        renderMeta(item);
        renderLanes(item);
      }
    },
    file_done(e) {
      const item = byId(e.id);
      if (!item) return;
      Object.assign(item, {
        status: "done",
        stage: null,
        progress: 1,
        language: e.language,
        target: e.target_language,
        segments: e.segments,
        outputs: e.outputs,
        duration: e.duration || item.duration,
      });
      if (e.translation_error) {
        const code = item.translationCode;
        const reason = code && dict["err." + code] ? t("err." + code) : e.translation_error;
        item.notes.push(t("note.translationFailed", { reason }));
      }
      renderQueue();
      if (state.selectedId === e.id) renderStage();
      renderDeckStatus();
    },
    file_error(e) {
      const item = byId(e.id);
      if (!item) return;
      Object.assign(item, { status: "error", stage: null, error: e.error });
      renderQueue();
      if (state.selectedId === e.id) renderStage();
    },
    file_cancelled(e) {
      const item = byId(e.id);
      if (!item) return;
      resetItem(item);
      item.status = "cancelled";
      renderQueue();
      if (state.selectedId === e.id) renderStage();
    },
    job_error(e) {
      const current = state.job?.currentId && byId(state.job.currentId);
      const victim = current && current.status === "active" ? current : byId(state.job?.ids?.[0]);
      if (victim) Object.assign(victim, { status: "error", stage: null, error: e.error });
      const key = "err." + e.error.code;
      toast(dict[key] ? t(key) : t("err.unexpected", { message: e.error.message }), "error");
      renderAll();
    },
    log(e) {
      const item = e.id && byId(e.id);
      if (!item) return;
      if (e.code === "provider_fallback") {
        item.notes.push(t("note.fallback", { provider: t("set.provider." + e.provider) }));
      } else if (e.code === "same_language") {
        item.notes.push(t("note.sameLanguage"));
      } else if (e.level === "warning" && e.code) {
        item.translationCode = e.code;
      }
      if (state.selectedId === e.id) renderNotice(item);
    },
    job_done(e) {
      state.running = false;
      const ids = state.job?.ids ?? [];
      state.job = null;
      for (const item of ids.map(byId)) {
        if (item && item.status === "active") resetItem(item);
      }
      renderAll();
      const firstOutput = e.report || e.outputs?.[0];
      if (e.quiet) return;
      if (e.cancelled) toast(t("toast.cancelled"), "info");
      else if (e.failed) toast(t("toast.partial", { done: e.done, total: e.done + e.failed }), "error", firstOutput);
      else if (e.done) toast(t("toast.done", { count: e.done }), "ok", firstOutput);
    },
  };

  window.AT = {
    receive(event) {
      try {
        handlers[event.type]?.(event);
      } catch (err) {
        console.error("Event handler failed", event.type, err);
      }
    },
  };

  // --------------------------------------------------------------- toasts
  function toast(text, tone = "ok", revealPath = null) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast";
    el.dataset.tone = tone;
    el.setAttribute("role", "status");
    const ic = tone === "error" ? "circle-alert" : tone === "info" ? "info" : "circle-check";
    el.innerHTML = `${icon(ic)}<span>${esc(text)}</span>${revealPath ? `<button class="btn" type="button">${esc(t("toast.openFolder"))}</button>` : ""}`;
    if (revealPath) $("button", el).addEventListener("click", () => api.reveal(revealPath));
    box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => el.remove(), revealPath ? 9000 : 3500);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast(t("toast.copied"), "ok");
  }

  // ---------------------------------------------------------- wiring
  let bound = false;
  function bindStatic() {
    if (bound) return;
    bound = true;
    $("#btn-settings").addEventListener("click", openSettings);
    $("#btn-add-files").addEventListener("click", chooseFiles);
    $("#btn-add-folder").addEventListener("click", chooseFolder);
    $("#btn-empty-files").addEventListener("click", chooseFiles);
    $("#btn-empty-folder").addEventListener("click", chooseFolder);
    $("#btn-start").addEventListener("click", startJob);
    $("#btn-clear").addEventListener("click", () => {
      if (state.running) return;
      state.queue = [];
      state.selectedId = null;
      renderAll();
    });
    $("#deck-output").addEventListener("click", openSettings);
    $("#settings-root").addEventListener("click", handleSettingsClick);

    $("#queue-list").addEventListener("click", (e) => {
      const remove = e.target.closest("[data-remove]");
      if (remove) return removeItem(remove.dataset.remove);
      const li = e.target.closest(".q-item");
      if (li) selectItem(li.dataset.id);
    });

    $("#deck-formats").addEventListener("click", (e) => {
      const fmt = e.target.closest("[data-fmt]");
      if (fmt && !fmt.disabled) toggleFormat(fmt.dataset.fmt);
    });

    $("#sel-source").addEventListener("click", (e) =>
      openSelect(e.currentTarget, {
        options: languageOptions({ value: "", label: t("deck.autoLong"), search: "auto" }),
        value: state.settings.source_language,
        search: true,
        onPick: (value) => saveSettings({ source_language: value }),
      }),
    );
    $("#sel-target").addEventListener("click", (e) =>
      openSelect(e.currentTarget, {
        options: languageOptions({ value: "", label: t("deck.noTranslation"), search: "none" }),
        value: state.settings.target_language,
        search: true,
        onPick: (value) => saveSettings({ target_language: value }),
      }),
    );
    $("#sel-model").addEventListener("click", (e) =>
      openSelect(e.currentTarget, {
        options: modelOptions(),
        value: state.settings.model,
        width: 340,
        onPick: (value) => saveSettings({ model: value }),
      }),
    );

    $("#fv-actions").addEventListener("click", (e) => {
      const action = e.target.closest("[data-action]")?.dataset.action;
      const item = selected();
      if (!action || !item) return;
      if (action === "copy-orig") copyText(item.segments.map((s) => s.text).join("\n"));
      if (action === "copy-tr") copyText(item.segments.map((s) => s.translation).join("\n"));
      if (action === "reveal") api.reveal(item.outputs[0]);
    });
    $("#fv-outputs").addEventListener("click", (e) => {
      const chip = e.target.closest("[data-open]");
      if (chip) api.open_path(chip.dataset.open);
    });

    // waveform ↔ transcript linking
    const body = $("#lanes-body");
    body.addEventListener("mouseover", (e) => {
      const row = e.target.closest(".lane-row");
      const item = selected();
      if (!row || !item) return;
      const seg = item.segments[Number(row.dataset.index)];
      if (seg) {
        hotRange = [seg.start, seg.end];
        drawWave();
      }
    });
    body.addEventListener("mouseleave", () => {
      hotRange = null;
      drawWave();
    });
    $("#wave").addEventListener("click", (e) => {
      const item = selected();
      if (!item?.segments.length) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const time = ((e.clientX - rect.left) / rect.width) * (item.duration || 0);
      let index = item.segments.findIndex((s) => s.end >= time);
      if (index < 0) index = item.segments.length - 1;
      const row = $(`.lane-row[data-index="${index}"]`, body);
      if (!row) return;
      row.scrollIntoView({ block: "center" });
      $$(".lane-row[data-hot]", body).forEach((r) => r.removeAttribute("data-hot"));
      row.setAttribute("data-hot", "");
      setTimeout(() => row.removeAttribute("data-hot"), 1600);
    });

    new ResizeObserver(() => drawWave()).observe($("#wave-wrap"));

    // drag & drop: Python receives the real paths; JS only draws the overlay
    const overlay = $("#drop-overlay");
    let depth = 0;
    const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
    window.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth++;
      overlay.setAttribute("data-show", "");
    });
    window.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) overlay.removeAttribute("data-show");
    });
    window.addEventListener("dragover", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      depth = 0;
      overlay.removeAttribute("data-show");
      api.drop_fallback?.(Array.from(e.dataTransfer?.files || []));
    });

    document.addEventListener("keydown", (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") {
        if (popover) return closePopover();
        if (state.settingsOpen) return closeSettings();
      }
      if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        e.shiftKey ? chooseFolder() : chooseFiles();
      } else if (mod && e.key === "Enter") {
        e.preventDefault();
        if (!$("#btn-start").disabled) startJob();
      } else if (mod && e.key === ",") {
        e.preventDefault();
        openSettings();
      } else if (e.key === "Delete" && state.selectedId && !state.settingsOpen && !popover) {
        const typing = document.activeElement?.matches?.("input, textarea");
        const selection = String(window.getSelection?.() || "");
        if (!typing && !selection) removeItem(state.selectedId);
      }
    });

    // live ETA refresh between progress events
    setInterval(() => state.running && renderDeckStatus(), 1000);
  }

  connect();
})();
