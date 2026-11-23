/* Demo backend for previewing the interface in a regular browser.
   Open index.html?demo (or ?demo=processing / ?demo=done) through any static server.
   Not loaded by the desktop app. */
(() => {
  "use strict";

  const LANGS = [
    ["en", "English", "Английский", "English"], ["ru", "Russian", "Русский", "Русский"],
    ["uk", "Ukrainian", "Украинский", "Українська"], ["be", "Belarusian", "Белорусский", "Беларуская"],
    ["kk", "Kazakh", "Казахский", "Қазақша"], ["uz", "Uzbek", "Узбекский", "Oʻzbekcha"],
    ["de", "German", "Немецкий", "Deutsch"], ["fr", "French", "Французский", "Français"],
    ["es", "Spanish", "Испанский", "Español"], ["it", "Italian", "Итальянский", "Italiano"],
    ["pt", "Portuguese", "Португальский", "Português"], ["nl", "Dutch", "Нидерландский", "Nederlands"],
    ["pl", "Polish", "Польский", "Polski"], ["cs", "Czech", "Чешский", "Čeština"],
    ["tr", "Turkish", "Турецкий", "Türkçe"], ["ar", "Arabic", "Арабский", "العربية"],
    ["he", "Hebrew", "Иврит", "עברית"], ["hi", "Hindi", "Хинди", "हिन्दी"],
    ["zh", "Chinese", "Китайский", "中文"], ["ja", "Japanese", "Японский", "日本語"],
    ["ko", "Korean", "Корейский", "한국어"], ["ka", "Georgian", "Грузинский", "ქართული"],
  ].map(([code, en, ru, native]) => ({ code, en, ru, native }));

  const MODELS = [
    ["tiny", 75, 5, 1, true], ["base", 145, 5, 2, false], ["small", 485, 4, 3, true],
    ["medium", 1530, 2, 4, false], ["large-v3-turbo", 1620, 3, 4, false], ["large-v3", 3100, 1, 5, false],
  ].map(([name, size_mb, speed, accuracy, downloaded]) => ({ name, size_mb, speed, accuracy, downloaded }));

  const LECTURE = [
    ["Welcome back. Today we're picking up where we left off last week, with orbital mechanics.",
      "С возвращением. Сегодня продолжим с того места, где остановились на прошлой неделе, — с орбитальной механики."],
    ["The key idea is surprisingly simple: an orbit is just falling and missing the ground.",
      "Ключевая идея на удивление проста: орбита — это падение, при котором ты всё время промахиваешься мимо Земли."],
    ["If you throw a ball fast enough, the Earth curves away beneath it before it can land.",
      "Если бросить мяч достаточно быстро, Земля успеет изогнуться под ним раньше, чем он упадёт."],
    ["For low Earth orbit, that speed is roughly seven point eight kilometers per second.",
      "Для низкой околоземной орбиты эта скорость — примерно семь и восемь десятых километра в секунду."],
    ["Now, here's the counterintuitive part that trips up almost everyone.",
      "А теперь контринтуитивная часть, на которой спотыкаются почти все."],
    ["To catch up with a spacecraft ahead of you, you actually need to slow down.",
      "Чтобы догнать корабль, который летит впереди, нужно на самом деле затормозить."],
    ["Slowing down drops you into a lower orbit, and lower orbits are faster.",
      "Торможение переводит вас на более низкую орбиту, а низкие орбиты быстрее."],
    ["Then you speed up again to climb back, and you arrive right behind the target.",
      "Потом вы снова разгоняетесь, поднимаетесь обратно и оказываетесь прямо за целью."],
    ["The crew of Gemini 4 learned this the hard way in 1965.",
      "Экипаж «Джемини-4» усвоил это на собственном опыте в 1965 году."],
    ["They pointed the capsule at the target, fired the thrusters, and watched it drift away.",
      "Они навели капсулу на цель, включили двигатели — и смотрели, как она уплывает прочь."],
    ["So let's draw this out and see why the math works the way it does.",
      "Давайте нарисуем это и разберёмся, почему математика работает именно так."],
    ["Grab your notebooks, because the next twenty minutes are going to be dense.",
      "Берите тетради: следующие двадцать минут будут плотными."],
  ];

  const FILES = [
    { name: "orbital-mechanics-lecture.mp4", kind: "video", size: 41_418_752, duration: 112 },
    { name: "voice-note-2026-11-02.m4a", kind: "audio", size: 2_412_544, duration: 151 },
    { name: "podcast-ep112-interview.mp3", kind: "audio", size: 104_857_600, duration: 4360 },
    { name: "conference-keynote.mkv", kind: "video", size: 1_288_490_188, duration: 2045 },
    { name: "interview_raw_take2.wav", kind: "audio", size: 88_604_672, duration: 502 },
  ].map((f, i) => ({ ...f, id: `demo${i}`, path: `C:\\Users\\you\\Videos\\${f.name}` }));

  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }

  function waveform(seed, n = 360) {
    const rand = rng(seed);
    const out = [];
    let word = 0;
    for (let i = 0; i < n; i++) {
      if (word <= 0) word = rand() < 0.12 ? -Math.floor(2 + rand() * 5) : Math.floor(4 + rand() * 14);
      if (word < 0) {
        out.push(0.03 + rand() * 0.05);
        word++;
      } else {
        const env = 0.45 + 0.55 * Math.sin((word / 18) * Math.PI);
        out.push(Math.min(1, env * (0.45 + rand() * 0.6)));
        word--;
      }
    }
    return out;
  }

  function segmentsFor(total, duration) {
    const step = Math.min(9, duration / (total + 1));
    return LECTURE.slice(0, total).map(([text, translation], i) => ({
      start: 4 + i * step,
      end: 4 + i * step + step * 0.9,
      text,
      translation,
    }));
  }

  class MockAPI {
    constructor(AT) {
      this.AT = AT;
      this.scenario = (location.search.match(/demo=(\w+)/) || [])[1] || "";
      this.settings = {
        model: "small", device: "auto", source_language: "", target_language: "ru", provider: "google",
        deepl_key: "", fallback: true, formats: ["txt", "srt"], report: true, include_original: true,
        output_dir: "", vad: true, recursive: true,
        ui_language: (location.search.match(/lang=(\w+)/) || [])[1] || "ru",
        theme: (location.search.match(/theme=(\w+)/) || [])[1] || "dark",
      };
      this.timer = null;
      this.cancelled = false;
    }

    emit(event) {
      this.AT.receive(event);
    }

    async init() {
      return {
        version: "2.0.0", settings: { ...this.settings }, languages: LANGS, models: MODELS,
        gpu: false, platform: "demo", models_dir: "C:\\Users\\you\\AppData\\Local\\AudioTranslator\\models",
        repo_url: "https://github.com/wissxi/AudioTranslator",
      };
    }

    async save_settings(patch) {
      Object.assign(this.settings, patch);
      return { ...this.settings };
    }

    async pick_files() {
      return FILES.slice(0, 3);
    }

    async pick_folder() {
      return FILES;
    }

    async pick_output_dir() {
      return "C:\\Users\\you\\Documents\\Transcripts";
    }

    async add_paths() {
      return FILES;
    }

    drop_fallback() {
      this.emit({ type: "files_added", files: FILES });
    }

    async reveal() {}
    async open_path() {}
    async open_url(url) {
      window.open(url, "_blank");
    }
    set_theme() {}

    ready() {
      if (this.scenario === "processing") this.stage("processing");
      if (this.scenario === "done") this.stage("done");
    }

    // Build a frozen state for screenshots.
    stage(kind) {
      const [lecture, note, ...rest] = FILES;
      this.emit({ type: "files_added", files: [lecture, note, ...rest], quiet: true });
      const ids = [note.id, lecture.id, rest[0].id, rest[1].id, rest[2].id];
      this.emit({ type: "job_started", total: ids.length, ids });
      this.emit({ type: "model_loading", model: "small", downloading: false });
      this.emit({ type: "model_ready", model: "small", device: "cpu", compute_type: "int8" });

      this.emit({ type: "file_started", id: note.id, index: 0, total: ids.length, name: note.name });
      this.emit({ type: "file_audio", id: note.id, duration: note.duration, waveform: waveform(7) });
      this.emit({
        type: "file_done", id: note.id, language: "en", target_language: "ru", provider: "google",
        segments: segmentsFor(3, note.duration), duration: note.duration,
        outputs: [`C:\\Users\\you\\Videos\\voice-note-2026-11-02.txt`, `C:\\Users\\you\\Videos\\voice-note-2026-11-02.ru.srt`],
      });

      this.emit({ type: "file_started", id: lecture.id, index: 1, total: ids.length, name: lecture.name });
      this.emit({ type: "file_audio", id: lecture.id, duration: lecture.duration, waveform: waveform(42) });
      this.emit({ type: "file_language", id: lecture.id, language: "en", probability: 0.98 });

      if (kind === "processing") {
        const segs = segmentsFor(12, lecture.duration);
        const shown = segs.slice(0, 9);
        shown.forEach((s) => this.emit({ type: "segment", id: lecture.id, start: s.start, end: s.end, text: s.text }));
        this.emit({ type: "file_progress", id: lecture.id, stage: "recognizing", progress: 0.62 });
        this.emit({ type: "file_error", id: rest[2].id, error: { code: "no_audio", message: "No audio track" } });
      } else {
        const segs = segmentsFor(12, lecture.duration);
        this.emit({
          type: "file_done", id: lecture.id, language: "en", target_language: "ru", provider: "google",
          segments: segs, duration: lecture.duration,
          outputs: [
            "C:\\Users\\you\\Videos\\orbital-mechanics-lecture.txt",
            "C:\\Users\\you\\Videos\\orbital-mechanics-lecture.ru.srt",
            "C:\\Users\\you\\Videos\\orbital-mechanics-lecture.en.srt",
          ],
        });
        this.emit({ type: "job_done", done: 2, failed: 0, cancelled: false, outputs: [], report: null, elapsed: 400, quiet: true });
      }
    }

    async start(items) {
      this.cancelled = false;
      const ids = items.map((i) => i.id);
      this.emit({ type: "job_started", total: ids.length, ids });
      const needDownload = !MODELS.find((m) => m.name === this.settings.model)?.downloaded;
      this.emit({ type: "model_loading", model: this.settings.model, downloading: needDownload });
      let progress = needDownload ? 0 : 1;
      let fileIndex = 0;
      let segIndex = 0;
      let phase = needDownload ? "download" : "ready";
      const outputs = [];

      this.timer = setInterval(() => {
        if (this.cancelled) {
          clearInterval(this.timer);
          if (fileIndex < items.length) this.emit({ type: "file_cancelled", id: items[fileIndex].id });
          this.emit({ type: "job_done", done: fileIndex, failed: 0, cancelled: true, outputs, report: null, elapsed: 3 });
          return;
        }
        if (phase === "download") {
          progress = Math.min(1, progress + 0.07);
          this.emit({ type: "model_download", model: this.settings.model, progress });
          if (progress >= 1) phase = "ready";
          return;
        }
        if (phase === "ready") {
          this.emit({ type: "model_ready", model: this.settings.model, device: "cpu", compute_type: "int8" });
          phase = "file";
          return;
        }
        const item = items[fileIndex];
        const file = FILES.find((f) => f.id === item.id) || { duration: 120, name: item.path };
        const segs = segmentsFor(LECTURE.length, file.duration);
        if (phase === "file") {
          this.emit({ type: "file_started", id: item.id, index: fileIndex, total: items.length, name: file.name });
          this.emit({ type: "file_audio", id: item.id, duration: file.duration, waveform: waveform(fileIndex * 13 + 5) });
          this.emit({ type: "file_language", id: item.id, language: "en", probability: 0.97 });
          phase = "segments";
          segIndex = 0;
          return;
        }
        if (phase === "segments") {
          const s = segs[segIndex];
          this.emit({ type: "segment", id: item.id, start: s.start, end: s.end, text: s.text });
          this.emit({ type: "file_progress", id: item.id, stage: "recognizing", progress: 0.04 + 0.8 * ((segIndex + 1) / segs.length) });
          segIndex++;
          if (segIndex >= segs.length) phase = "translate";
          return;
        }
        if (phase === "translate") {
          this.emit({ type: "file_progress", id: item.id, stage: "translating", progress: 0.92 });
          phase = "save";
          return;
        }
        const target = this.settings.target_language || null;
        const out = [`C:\\Users\\you\\Videos\\${file.name.replace(/\.\w+$/, "")}.txt`];
        outputs.push(...out);
        this.emit({
          type: "file_done", id: item.id, language: "en", target_language: target, provider: "google",
          segments: target ? segs : segs.map((s) => ({ ...s, translation: "" })),
          outputs: out, duration: file.duration,
        });
        fileIndex++;
        phase = "file";
        if (fileIndex >= items.length) {
          clearInterval(this.timer);
          this.emit({ type: "job_done", done: items.length, failed: 0, cancelled: false, outputs, report: "C:\\Users\\you\\Videos\\translations.txt", elapsed: 12 });
        }
      }, 160);
      return { ok: true };
    }

    async cancel() {
      this.cancelled = true;
    }
  }

  window.MockAPI = MockAPI;
})();
