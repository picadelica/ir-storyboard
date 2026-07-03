// Заливка ячейки матрицы/досье по объёму записей.
// Ячейка — СПЛОШНОГО цвета (никаких градиентов: текст на границе тёмного и
// светлого нечитаем). Зелёный — интенсивность ∝ объёму относительно среднего
// у клиента (кламп ±20%): меньше записей → светлее, больше → темнее. Доля
// серых карточек (пробелов) отдаётся числом greyShare — компонент рисует её
// отдельной тонкой полоской, не смешивая с фоном.
//
// Палитра — editorial: приглушённый шалфейно-лесной зелёный (hue 152) на тёплой
// бумаге; самые наполненные ячейки уходят в глубокий тёмный зелёный, и текст на
// них становится светлым. Серый — тёплый песочный, под канву #fdf8f8.

const GREEN_HUE = 152;
const GREEN_SAT = 26;     // приглушённая, не «салатовая» насыщенность
const GREEN_LIGHT = 90;   // HSL lightness при объёме ≤ среднее−20%
const GREEN_DARK = 38;    // HSL lightness при объёме ≥ среднее+20%
export const GREY = "hsl(42, 16%, 87%)";
export const GREY_DEEP = "hsl(42, 14%, 62%)";  // насыщенный песочный — полоска пробелов
const GREY_FG = "#6B6558";

// Среднее число записей на НЕпустую ячейку (пустые в среднее не входят).
export function recordAvg(totals: number[]): number {
  const nz = totals.filter(t => t > 0);
  if (!nz.length) return 0;
  return nz.reduce((a, b) => a + b, 0) / nz.length;
}

export interface CellFill {
  background: string;   // CSS background — всегда сплошной цвет
  fg: string;           // читаемый цвет текста (название и цифра)
  greyShare: number;    // доля серых карточек 0..1 — для полоски пробелов
  empty: boolean;       // в ячейке нет записей
}

export function cellFill(nGreen: number, nGrey: number, avg: number): CellFill {
  const total = nGreen + nGrey;
  if (total === 0) return { background: "transparent", fg: "#8B877C", greyShare: 0, empty: true };

  const greyShare = nGrey / total;
  // ячейка целиком из пробелов — песочная
  if (nGreen === 0) return { background: GREY, fg: GREY_FG, greyShare, empty: false };

  const t = avg > 0 ? Math.max(0, Math.min(1, (total - 0.8 * avg) / (0.4 * avg))) : 0.5;
  const L = GREEN_LIGHT - t * (GREEN_LIGHT - GREEN_DARK);
  const background = `hsl(${GREEN_HUE}, ${GREEN_SAT}%, ${L.toFixed(1)}%)`;
  // тёмная ячейка → светлый текст; светлая → глубокий зелёный
  const fg = L <= 56 ? "#F5F2EA" : L <= 74 ? "#1C3E2E" : "#2F5D46";
  return { background, fg, greyShare, empty: false };
}
