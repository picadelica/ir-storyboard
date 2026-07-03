// Заливка ячейки матрицы/досье по объёму записей.
// Зелёный — интенсивность ∝ объёму относительно среднего у клиента (кламп ±20%):
// меньше записей → светлее, больше → темнее. Если в ячейке есть серые карточки —
// диагональный градиент: зелёный из левого нижнего угла, серый из правого верхнего;
// граница по доле карточек (зелёные/серые).
//
// Палитра — editorial: приглушённый шалфейно-лесной зелёный (hue 152) на тёплой
// бумаге; самые наполненные ячейки уходят в глубокий тёмный зелёный, и цифра на
// них становится светлой. Серый — тёплый песочный, под канву #fdf8f8.

const GREEN_HUE = 152;
const GREEN_SAT = 26;     // приглушённая, не «салатовая» насыщенность
const GREEN_LIGHT = 90;   // HSL lightness при объёме ≤ среднее−20%
const GREEN_DARK = 38;    // HSL lightness при объёме ≥ среднее+20%
const GREY = "hsl(42, 16%, 87%)";
const GREY_FG = "#6B6558";

// Среднее число записей на НЕпустую ячейку (пустые в среднее не входят).
export function recordAvg(totals: number[]): number {
  const nz = totals.filter(t => t > 0);
  if (!nz.length) return 0;
  return nz.reduce((a, b) => a + b, 0) / nz.length;
}

export interface CellFill {
  background: string;   // CSS background (solid hsl или linear-gradient)
  fg: string;           // читаемый цвет для крупной цифры (низ ячейки)
  labelFg: string;      // читаемый цвет для названия-лейбла (верх ячейки)
  empty: boolean;       // в ячейке нет записей
}

export function cellFill(nGreen: number, nGrey: number, avg: number): CellFill {
  const total = nGreen + nGrey;
  if (total === 0) return { background: "transparent", fg: "#B4B2A9", labelFg: "#8B877C", empty: true };

  const t = avg > 0 ? Math.max(0, Math.min(1, (total - 0.8 * avg) / (0.4 * avg))) : 0.5;
  const L = GREEN_LIGHT - t * (GREEN_LIGHT - GREEN_DARK);
  const green = `hsl(${GREEN_HUE}, ${GREEN_SAT}%, ${L.toFixed(1)}%)`;
  // тёмная ячейка → светлая цифра; светлая → глубокий зелёный текст
  const greenFg = L <= 56 ? "#F5F2EA" : L <= 74 ? "#1C3E2E" : "#2F5D46";

  if (nGrey === 0) return { background: green, fg: greenFg, labelFg: greenFg, empty: false };
  if (nGreen === 0) return { background: GREY, fg: GREY_FG, labelFg: GREY_FG, empty: false };

  // Смешанная ячейка: серый опускается сверху (доля по числу серых карточек),
  // зелёный снизу. Вертикаль (не диагональ) — лейбл наверху обычно на сером,
  // цифра внизу обычно на зелёном. Если одна из полос слишком тонкая, текст
  // выползает на соседнюю — тогда цвет берём от доминирующей полосы.
  const p = Math.round((nGreen / total) * 100);
  const lo = Math.max(0, p - 6);
  const hi = Math.min(100, p + 6);
  const background = `linear-gradient(to top, ${green} 0%, ${green} ${lo}%, ${GREY} ${hi}%, ${GREY} 100%)`;
  const fg = p >= 40 ? greenFg : GREY_FG;                    // цифре нужна зелёная полоса ≥40%
  const labelFg = (100 - p) >= 15 ? GREY_FG : greenFg;       // лейблу — серая ≥15%
  return { background, fg, labelFg, empty: false };
}
