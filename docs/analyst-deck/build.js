const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa6");

// ── palette (Ink / Teal — fits an IR fact-verification tool) ──
const INK = "16222E", INK2 = "22333F", PAPER = "FFFFFF", PANEL = "F6F8FA";
const MUTE = "5B6B7A", LINE = "E3E8EE", TEAL = "0E8A8A", BLUE = "2563EB";
const GREEN = "2E7D55", RED = "C0392B", GREY = "94A3B8", AMBER = "B7791F";
const HFONT = "Georgia", BFONT = "Calibri";

async function png(Icon, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Icon, { color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

async function main() {
  // pre-render icons
  const I = {};
  const want = {
    layers: FA.FaLayerGroup, shield: FA.FaShieldHalved, search: FA.FaMagnifyingGlass,
    building: FA.FaBuilding, chat: FA.FaComments, compass: FA.FaCompass,
    import: FA.FaFileImport, check: FA.FaCircleCheck, x: FA.FaCircleXmark,
    warn: FA.FaTriangleExclamation, link: FA.FaLink, wand: FA.FaWandMagicSparkles,
    userslash: FA.FaUserSlash, arrow: FA.FaArrowRightLong, list: FA.FaListCheck,
    globe: FA.FaGlobe, doc: FA.FaFileLines, db: FA.FaDatabase, hammer: FA.FaHammer,
    box: FA.FaBoxOpen, route: FA.FaRoute, quote: FA.FaQuoteLeft, gauge: FA.FaGaugeHigh,
  };
  for (const [k, v] of Object.entries(want)) {
    I[k] = { white: await png(v, "#FFFFFF"), teal: await png(v, "#0E8A8A"),
             ink: await png(v, "#16222E"), green: await png(v, "#2E7D55"),
             red: await png(v, "#C0392B"), grey: await png(v, "#94A3B8"),
             amber: await png(v, "#B7791F"), blue: await png(v, "#2563EB") };
  }

  const p = new pptxgen();
  p.defineLayout({ name: "W", width: 13.333, height: 7.5 });
  p.layout = "W";
  p.author = "IR Storyboard";
  p.title = "IR Storyboard — гайд для аналитика";
  const W = 13.333, H = 7.5, M = 0.7;
  const shadow = () => ({ type: "outer", color: "9AA7B4", blur: 8, offset: 2, angle: 90, opacity: 0.18 });

  // header for light content slides
  function head(s, num, kicker, title) {
    s.addText(String(num).padStart(2, "0"), { x: M, y: 0.5, w: 0.9, h: 0.9, fontFace: HFONT,
      fontSize: 30, color: TEAL, bold: true, align: "left", valign: "middle", margin: 0 });
    s.addText(kicker.toUpperCase(), { x: M + 0.95, y: 0.52, w: 11, h: 0.3, fontFace: BFONT,
      fontSize: 11, color: TEAL, bold: true, charSpacing: 3, margin: 0 });
    s.addText(title, { x: M + 0.93, y: 0.78, w: 11.4, h: 0.7, fontFace: HFONT,
      fontSize: 28, color: INK, bold: true, margin: 0 });
  }
  // a card
  function card(s, x, y, w, h, fill = PAPER) {
    s.addShape(p.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill },
      line: { color: LINE, width: 1 }, rectRadius: 0.08, shadow: shadow() });
  }
  function chipIcon(s, icon, x, y, d = 0.62, circle = TEAL) {
    s.addShape(p.shapes.OVAL, { x, y, w: d, h: d, fill: { color: circle } });
    s.addImage({ data: icon, x: x + d * 0.26, y: y + d * 0.26, w: d * 0.48, h: d * 0.48 });
  }

  // ───────────────────────── Slide 1 — title (dark) ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: INK };
    // motif: faint stacked layer bars on the right
    for (let i = 0; i < 6; i++)
      s.addShape(p.shapes.ROUNDED_RECTANGLE, { x: 9.0 + i * 0.18, y: 1.5 + i * 0.55, w: 3.2 - i * 0.1, h: 0.34,
        fill: { color: i % 2 ? TEAL : "2E4150" }, rectRadius: 0.04, line: { type: "none" } });
    s.addText("IR STORYBOARD", { x: M, y: 1.7, w: 8, h: 0.4, fontFace: BFONT, fontSize: 14,
      color: TEAL, bold: true, charSpacing: 5, margin: 0 });
    s.addText("Гайд для аналитика", { x: M, y: 2.15, w: 8.2, h: 1.5, fontFace: HFONT, fontSize: 52,
      color: PAPER, bold: true, margin: 0 });
    s.addText("Что построено и как этим пользоваться", { x: M, y: 3.65, w: 8, h: 0.6, fontFace: BFONT,
      fontSize: 20, color: "C9D4DE", margin: 0 });
    s.addShape(p.shapes.LINE, { x: M + 0.02, y: 4.5, w: 2.4, h: 0, line: { color: TEAL, width: 2.5 } });
    s.addText("Персистентная нарративная матрица + контур доверия к фактам.\nГолые факты, со ссылкой, подтверждённые аналитиком.",
      { x: M, y: 4.7, w: 7.6, h: 1.0, fontFace: BFONT, fontSize: 14, color: "9FB0BD", lineSpacingMultiple: 1.2, margin: 0 });
  }

  // ───────────────────────── Slide 2 — big idea ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 1, "Большая идея", "Две опоры инструмента");
    s.addText("IR Storyboard ведёт по каждому клиенту живую картину — и держит её честной.",
      { x: M, y: 1.75, w: 12, h: 0.5, fontFace: BFONT, fontSize: 15, color: MUTE, italic: true, margin: 0 });
    const cy = 2.5, ch = 4.0, cw = 5.85;
    // card A
    card(s, M, cy, cw, ch);
    chipIcon(s, I.layers.white, M + 0.45, cy + 0.45);
    s.addText("Матрица", { x: M + 1.25, y: cy + 0.5, w: cw - 1.6, h: 0.5, fontFace: HFONT, fontSize: 22, color: INK, bold: true, margin: 0 });
    s.addText([
      { text: "8 слоёв близости × 3 подсекции = 24 ячейки.", options: { bullet: true, breakLine: true } },
      { text: "От личной истории фаундера до PEST-контекста — единая картина клиента.", options: { bullet: true, breakLine: true } },
      { text: "Каждый факт тегирован: подтверждён / чувствителен / пробел.", options: { bullet: true } },
    ], { x: M + 0.5, y: cy + 1.4, w: cw - 1.0, h: ch - 1.7, fontFace: BFONT, fontSize: 14.5, color: "2C3A47", paraSpaceAfter: 10 });
    // card B
    const bx = M + cw + 0.5;
    card(s, bx, cy, cw, ch);
    chipIcon(s, I.shield.white, bx + 0.45, cy + 0.45, 0.62, GREEN);
    s.addText("Доверие", { x: bx + 1.25, y: cy + 0.5, w: cw - 1.6, h: 0.5, fontFace: HFONT, fontSize: 22, color: INK, bold: true, margin: 0 });
    s.addText([
      { text: "В матрицу попадают только проверенные факты со ссылкой.", options: { bullet: true, breakLine: true } },
      { text: "Аудит второй LLM-моделью ловит склейку сущностей и выдумку.", options: { bullet: true, breakLine: true } },
      { text: "Голые факты, не эмоции. Решение всегда за аналитиком.", options: { bullet: true } },
    ], { x: bx + 0.5, y: cy + 1.4, w: cw - 1.0, h: ch - 1.7, fontFace: BFONT, fontSize: 14.5, color: "2C3A47", paraSpaceAfter: 10 });
  }

  // ───────────────────────── Slide 3 — navigation ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 2, "Навигация", "Четыре зоны — где что лежит");
    const zones = [
      { ic: I.compass.white, c: TEAL, t: "Map", d: "About — карточка компании.\nMatrix — нарративная матрица." },
      { ic: I.import.white, c: BLUE, t: "Build", d: "LLM-отчёт · YouTube · Audio · Research · Work — наполнение фактами." },
      { ic: I.search.white, c: AMBER, t: "Health", d: "Scorecard · Punch-list · Проверка фактов · Interview Qs — качество." },
      { ic: I.box.white, c: GREEN, t: "Deliver", d: "Brief · Artifacts · Plan — артефакты для NotebookLM и клиента." },
    ];
    const cw = 2.85, gap = 0.27, y = 2.15, ch = 3.7;
    let x = M;
    zones.forEach(z => {
      card(s, x, y, cw, ch);
      chipIcon(s, z.ic, x + 0.35, y + 0.4, 0.6, z.c);
      s.addText(z.t, { x: x + 1.1, y: y + 0.42, w: cw - 1.2, h: 0.55, fontFace: HFONT, fontSize: 20, color: INK, bold: true, margin: 0 });
      s.addText(z.d, { x: x + 0.35, y: y + 1.25, w: cw - 0.7, h: ch - 1.5, fontFace: BFONT, fontSize: 13, color: "33424F", lineSpacingMultiple: 1.15, margin: 0 });
      x += cw + gap;
    });
    s.addText([
      { text: "Вверху справа: ", options: { bold: true } },
      { text: "Methodology (справочник методики) и переключатель Analyst / Present (режим показа клиенту)." },
    ], { x: M, y: 6.15, w: 12, h: 0.5, fontFace: BFONT, fontSize: 13, color: MUTE, margin: 0 });
  }

  // ───────────────────────── Slide 4 — matrix ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 3, "Нарративная матрица", "8 слоёв близости × 3 подсекции");
    // left text
    s.addText([
      { text: "Концентрические слои близости", options: { bold: true, color: INK, breakLine: true } },
      { text: "от личной истории фаундера (центр) до политико-экономического контекста (край). В каждом слое — 3 подсекции, всего 24 ячейки.", options: { breakLine: true } },
      { text: " ", options: { breakLine: true, fontSize: 8 } },
      { text: "Provenance обязателен", options: { bold: true, color: INK, breakLine: true } },
      { text: "онлайн-факт без ссылки или сниппета не принимается. YouTube/аудио закреплены цитатой и таймкодом.", options: {} },
    ], { x: M, y: 2.2, w: 6.2, h: 3.6, fontFace: BFONT, fontSize: 15, color: "33424F", lineSpacingMultiple: 1.25, paraSpaceAfter: 6, margin: 0 });
    // right: flag legend cards
    const fx = 7.4, fw = 5.2; let fy = 2.15;
    const flags = [
      { c: GREEN, ic: I.check.white, t: "green — подтверждённый факт", d: "нейтральный/позитивный, со ссылкой" },
      { c: RED, ic: I.warn.white, t: "red — чувствительный факт", d: "эмоциональное ядро; требует обоснования" },
      { c: GREY, ic: I.x.white, t: "grey — явный пробел", d: "что ещё нужно узнать (process, не отчёт)" },
    ];
    flags.forEach(f => {
      card(s, fx, fy, fw, 1.05);
      chipIcon(s, f.ic, fx + 0.3, fy + 0.22, 0.6, f.c);
      s.addText(f.t, { x: fx + 1.05, y: fy + 0.18, w: fw - 1.2, h: 0.42, fontFace: BFONT, fontSize: 15, bold: true, color: INK, margin: 0 });
      s.addText(f.d, { x: fx + 1.05, y: fy + 0.58, w: fw - 1.2, h: 0.35, fontFace: BFONT, fontSize: 12.5, color: MUTE, margin: 0 });
      fy += 1.25;
    });
  }

  // ───────────────────────── Slide 5 — ingest channels ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 4, "Наполнение", "Как факты попадают в матрицу");
    const chans = [
      { ic: I.doc.white, t: "LLM-отчёт", d: "deep-research .docx: факты + цитаты + источники" },
      { ic: I.chat.white, t: "YouTube", d: "транскрипт → факт с цитатой и таймкодом" },
      { ic: I.db.white, t: "Audio", d: "запись интервью → транскрипт → факты" },
      { ic: I.globe.white, t: "Research", d: "веб-поиск (Tavily) по запросу" },
    ];
    const cw = 2.85, gap = 0.27, y = 2.15, ch = 2.5; let x = M;
    chans.forEach(c => {
      card(s, x, y, cw, ch);
      chipIcon(s, c.ic, x + 0.35, y + 0.35, 0.58, TEAL);
      s.addText(c.t, { x: x + 0.35, y: y + 1.05, w: cw - 0.7, h: 0.4, fontFace: HFONT, fontSize: 17, bold: true, color: INK, margin: 0 });
      s.addText(c.d, { x: x + 0.35, y: y + 1.5, w: cw - 0.7, h: 0.9, fontFace: BFONT, fontSize: 12.5, color: "33424F", lineSpacingMultiple: 1.12, margin: 0 });
      x += cw + gap;
    });
    // gate band
    card(s, M, 5.0, 12.0 - 0.05, 1.55, PANEL);
    chipIcon(s, I.shield.white, M + 0.35, 5.3, 0.62, AMBER);
    s.addText("Ворота на входе", { x: M + 1.2, y: 5.25, w: 10.5, h: 0.4, fontFace: HFONT, fontSize: 18, bold: true, color: INK, margin: 0 });
    s.addText("Непроверенное или похожее на «двойника» придерживается на ревью — в матрицу автоматом не попадает. Сначала факт, потом доверие.",
      { x: M + 1.2, y: 5.68, w: 10.6, h: 0.7, fontFace: BFONT, fontSize: 13.5, color: "33424F", margin: 0 });
  }

  // ───────────────────────── Slide 6 — trust loop ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 5, "Контур доверия", "Health → «Проверка фактов»");
    const steps = [
      { n: "1", ic: I.search.white, t: "Аудит склейки", d: "вторая LLM-модель, скептик: ловит, где факт про другое лицо/компанию" },
      { n: "2", ic: I.globe.white, t: "Веб-проверка", d: "Tavily + грунтованный вердикт: confirmed / refuted / unresolved" },
      { n: "3", ic: I.link.white, t: "Дедуп и слияние", d: "околодубли → один факт; больше независимых источников = сильнее" },
      { n: "4", ic: I.building.white, t: "Якорь идентичности", d: "карточки: компания, фаундеры, двойники — точка опоры" },
    ];
    const cw = 2.85, gap = 0.27, y = 2.2, ch = 3.0; let x = M;
    steps.forEach(st => {
      card(s, x, y, cw, ch);
      chipIcon(s, st.ic, x + 0.32, y + 0.32, 0.56, TEAL);
      s.addText(st.n, { x: x + cw - 0.85, y: y + 0.2, w: 0.7, h: 0.7, fontFace: HFONT, fontSize: 30, color: LINE, bold: true, align: "right", margin: 0 });
      s.addText(st.t, { x: x + 0.32, y: y + 1.0, w: cw - 0.6, h: 0.7, fontFace: HFONT, fontSize: 16.5, bold: true, color: INK, margin: 0 });
      s.addText(st.d, { x: x + 0.32, y: y + 1.65, w: cw - 0.6, h: 1.2, fontFace: BFONT, fontSize: 12.5, color: "33424F", lineSpacingMultiple: 1.12, margin: 0 });
      x += cw + gap;
    });
    s.addText("Подозрительные факты помечаются — аналитик решает: снять или оставить. Транскриптные факты (цитата+таймкод) не трогаются.",
      { x: M, y: 5.55, w: 12, h: 0.6, fontFace: BFONT, fontSize: 13.5, color: MUTE, italic: true, margin: 0 });
  }

  // ───────────────────────── Slide 7 — Khachuyan hands-on (dark accent) ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: INK };
    s.addText("ПРАКТИКА", { x: M, y: 0.65, w: 6, h: 0.35, fontFace: BFONT, fontSize: 13, color: TEAL, bold: true, charSpacing: 4, margin: 0 });
    s.addText("Поймай Хачуяна", { x: M, y: 1.0, w: 9, h: 0.8, fontFace: HFONT, fontSize: 34, color: PAPER, bold: true, margin: 0 });
    // big left icon
    chipIcon(s, I.userslash.white, M, 2.3, 1.1, RED);
    s.addText([
      { text: "Открой ", options: {} },
      { text: "gonka.AI → Health → «Проверка фактов» → «Запустить проверку».", options: { bold: true, color: PAPER } },
    ], { x: M + 1.45, y: 2.35, w: 10.6, h: 0.5, fontFace: BFONT, fontSize: 16, color: "C9D4DE", margin: 0 });
    s.addText([
      { text: "Через ~30 секунд увидишь: ", options: {} },
      { text: "Артур Хачуян приписан как фаундер Gonka", options: { bold: true, color: "FF9A8B" } },
      { text: " — это склейка с другим публичным лицом (реальные основатели — братья Либерман). " },
      { text: "Факт настолько нелепый, что виден сразу.", options: { bold: true, color: PAPER } },
    ], { x: M + 1.45, y: 2.95, w: 10.5, h: 1.4, fontFace: BFONT, fontSize: 15.5, color: "AEBDC8", lineSpacingMultiple: 1.3, margin: 0 });
    // takeaway band
    card(s, M, 5.0, 12.0 - 0.05, 1.7, INK2);
    s.addText([
      { text: "Что сделать:  ", options: { bold: true, color: TEAL } },
      { text: "сними кластер Хачуяна (кнопка «снять») — досье и гайд интервью сразу станут честнее.", options: { color: "D7E0E7" } },
    ], { x: M + 0.4, y: 5.25, w: 11.2, h: 0.5, fontFace: BFONT, fontSize: 14.5, margin: 0 });
    s.addText([
      { text: "Зачем мы это оставили:  ", options: { bold: true, color: TEAL } },
      { text: "инструмент предлагает — решает аналитик. Мы намеренно не чистили данные: доверяй, но проверяй каждый факт по ссылке.", options: { color: "AEBDC8" } },
    ], { x: M + 0.4, y: 5.85, w: 11.3, h: 0.7, fontFace: BFONT, fontSize: 14, lineSpacingMultiple: 1.15, margin: 0 });
  }

  // ───────────────────────── Slide 8 — company About ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 6, "Карточка компании", "About — бизнес-профиль, без нарратива");
    // left: sections grid
    s.addText("Шесть бизнес-секций", { x: M, y: 2.15, w: 6, h: 0.4, fontFace: HFONT, fontSize: 17, bold: true, color: INK, margin: 0 });
    const secs = ["Профиль", "Сайты и каналы", "Финансирование", "История / майлстоны", "Продукт и рынок", "Метрики"];
    const gw = 2.7, gh = 0.7, gx0 = M, gy0 = 2.65;
    secs.forEach((t, i) => {
      const gx = gx0 + (i % 2) * (gw + 0.2), gy = gy0 + Math.floor(i / 2) * (gh + 0.2);
      card(s, gx, gy, gw, gh, PANEL);
      s.addText(t, { x: gx + 0.2, y: gy, w: gw - 0.3, h: gh, fontFace: BFONT, fontSize: 13, bold: true, color: "2C3A47", valign: "middle", margin: 0 });
    });
    // right: two ways
    const rx = 6.85, rw = 5.78;
    card(s, rx, 2.15, rw, 1.85);
    chipIcon(s, I.list.white, rx + 0.32, 2.4, 0.56, TEAL);
    s.addText("Руками", { x: rx + 1.05, y: 2.4, w: rw - 1.2, h: 0.45, fontFace: HFONT, fontSize: 17, bold: true, color: INK, margin: 0 });
    s.addText("«+ факт» в любой секции: значение + дата + ссылка-источник. Есть ссылка → факт verified. Плюс ссылки первоисточников и правка заголовка.",
      { x: rx + 0.32, y: 3.0, w: rw - 0.6, h: 0.95, fontFace: BFONT, fontSize: 13, color: "33424F", lineSpacingMultiple: 1.15, margin: 0 });
    card(s, rx, 4.15, rw, 2.4);
    chipIcon(s, I.wand.white, rx + 0.32, 4.4, 0.56, BLUE);
    s.addText("Авто-наполнить", { x: rx + 1.05, y: 4.4, w: rw - 1.2, h: 0.45, fontFace: HFONT, fontSize: 17, bold: true, color: INK, margin: 0 });
    s.addText([
      { text: "Три источника: уже собранное + веб-поиск + вставленный документ/URL.", options: { bullet: true, breakLine: true } },
      { text: "Только факты с реальной ссылкой (механический фильтр) — выдумка отбрасывается.", options: { bullet: true, breakLine: true } },
      { text: "Предложения → ты отмечаешь нужное → коммит. 100% уверенность.", options: { bullet: true } },
    ], { x: rx + 0.32, y: 5.0, w: rw - 0.6, h: 1.5, fontFace: BFONT, fontSize: 12.8, color: "33424F", paraSpaceAfter: 7, margin: 0 });
  }

  // ───────────────────────── Slide 9 — interview guide ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: PAPER };
    head(s, 7, "Гайд интервью", "Грунтован на проверенной матрице");
    // left
    card(s, M, 2.15, 6.1, 4.5);
    chipIcon(s, I.quote.white, M + 0.35, 2.45, 0.58, TEAL);
    s.addText("Каждый вопрос опирается на факт", { x: M + 1.1, y: 2.45, w: 4.8, h: 0.6, fontFace: HFONT, fontSize: 17, bold: true, color: INK, valign: "middle", margin: 0 });
    s.addText([
      { text: "Под вопросом — «основано на N факт(ах)»: видно, на чём он держится.", options: { bullet: true, breakLine: true } },
      { text: "Модель не выдумывает чисел/имён — чего нет в фактах, спрашивает у фаундера.", options: { bullet: true, breakLine: true } },
      { text: "Вопросы прыгают в ячейки матрицы — закрываешь пробел на месте.", options: { bullet: true } },
    ], { x: M + 0.4, y: 3.35, w: 5.4, h: 3.0, fontFace: BFONT, fontSize: 13.8, color: "2C3A47", paraSpaceAfter: 11, lineSpacingMultiple: 1.12, margin: 0 });
    // right
    const rx = 7.2, rw = 5.4;
    card(s, rx, 2.15, rw, 4.5, INK);
    s.addText("Структура гайда", { x: rx + 0.4, y: 2.4, w: rw - 0.8, h: 0.45, fontFace: HFONT, fontSize: 16, bold: true, color: TEAL, margin: 0 });
    s.addText([
      { text: "Досье", options: { bold: true, color: PAPER, breakLine: true } },
      { text: "кто фаундер и компания — сжато\n", options: { color: "AEBDC8", breakLine: true } },
      { text: "Диагноз", options: { bold: true, color: PAPER, breakLine: true } },
      { text: "что покрыто, что зияет, приоритеты\n", options: { color: "AEBDC8", breakLine: true } },
      { text: "Дуги близости", options: { bold: true, color: PAPER, breakLine: true } },
      { text: "вопросы по слоям + follow-ups", options: { color: "AEBDC8" } },
    ], { x: rx + 0.4, y: 3.0, w: rw - 0.8, h: 2.6, fontFace: BFONT, fontSize: 14, lineSpacingMultiple: 1.15, paraSpaceAfter: 4, margin: 0 });
    s.addText("Замкнутая петля: почистил матрицу → гайд авто-улучшается.",
      { x: rx + 0.4, y: 5.95, w: rw - 0.8, h: 0.5, fontFace: BFONT, fontSize: 12.5, italic: true, color: "8BA0AE", margin: 0 });
  }

  // ───────────────────────── Slide 10 — workflow + discipline (dark) ─────────────────────────
  {
    const s = p.addSlide(); s.background = { color: INK };
    s.addText("РАБОЧИЙ ЦИКЛ", { x: M, y: 0.6, w: 8, h: 0.35, fontFace: BFONT, fontSize: 13, color: TEAL, bold: true, charSpacing: 4, margin: 0 });
    s.addText("Шесть шагов аналитика", { x: M, y: 0.95, w: 11, h: 0.7, fontFace: HFONT, fontSize: 30, color: PAPER, bold: true, margin: 0 });
    const steps = ["Выбери клиента", "Наполни: ingest + About", "Проверь факты, сними двойников", "Сгенерируй гайд", "Веди интервью", "Собери артефакты"];
    const cw = 3.78, gap = 0.25, ch = 1.25;
    steps.forEach((t, i) => {
      const x = M + (i % 3) * (cw + gap), y = 2.05 + Math.floor(i / 3) * (ch + 0.25);
      s.addShape(p.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: ch, fill: { color: INK2 }, line: { color: "33485A", width: 1 }, rectRadius: 0.06 });
      s.addText(String(i + 1), { x: x + 0.25, y: y + 0.22, w: 0.7, h: 0.8, fontFace: HFONT, fontSize: 30, color: TEAL, bold: true, margin: 0 });
      s.addText(t, { x: x + 1.0, y: y + 0.15, w: cw - 1.2, h: ch - 0.3, fontFace: BFONT, fontSize: 14, color: "E2E8EE", valign: "middle", lineSpacingMultiple: 1.05, margin: 0 });
    });
    // discipline band
    s.addShape(p.shapes.ROUNDED_RECTANGLE, { x: M, y: 5.25, w: 12.0 - 0.05, h: 1.5, fill: { color: TEAL }, rectRadius: 0.08 });
    s.addText("Дисциплина", { x: M + 0.4, y: 5.45, w: 3, h: 0.5, fontFace: HFONT, fontSize: 18, color: PAPER, bold: true, margin: 0 });
    s.addText("Только проверенные факты, со ссылкой · аудит — второе мнение · аналитик подтверждает · голые факты, не эмоции.",
      { x: M + 0.4, y: 5.95, w: 11.3, h: 0.7, fontFace: BFONT, fontSize: 14.5, color: "EAFBFB", lineSpacingMultiple: 1.15, margin: 0 });
    s.addText("Доступ: по логину Telegram-группы · прод на сервере агентства.",
      { x: M, y: 6.95, w: 12, h: 0.35, fontFace: BFONT, fontSize: 11, color: "6E8492", margin: 0 });
  }

  await p.writeFile({ fileName: "IR-Storyboard-гайд-аналитика.pptx" });
  console.log("written");
}
main().catch(e => { console.error(e); process.exit(1); });
