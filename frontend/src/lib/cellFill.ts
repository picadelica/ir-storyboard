// Заливка ячейки матрицы/досье по объёму записей.
// Зелёный — интенсивность ∝ объёму относительно среднего у клиента (кламп ±20%):
// меньше записей → светлее, больше → темнее. Если в ячейке есть серые карточки —
// диагональный градиент: зелёный из левого нижнего угла, серый из правого верхнего;
// граница по доле карточек (зелёные/серые).

const GREEN_LIGHT = 88;   // HSL lightness при объёме ≤ среднее−20%
const GREEN_DARK = 58;    // HSL lightness при объёме ≥ среднее+20%
const GREY = "hsl(45, 10%, 85%)";
const GREY_FG = "#5F5E5A";

// Среднее число записей на НЕпустую ячейку (пустые в среднее не входят).
export function recordAvg(totals: number[]): number {
  const nz = totals.filter(t => t > 0);
  if (!nz.length) return 0;
  return nz.reduce((a, b) => a + b, 0) / nz.length;
}

export interface CellFill {
  background: string;   // CSS background (solid hsl или linear-gradient)
  fg: string;           // читаемый цвет для центральной цифры
  empty: boolean;       // в ячейке нет записей
}

export function cellFill(nGreen: number, nGrey: number, avg: number): CellFill {
  const total = nGreen + nGrey;
  if (total === 0) return { background: "transparent", fg: "#B4B2A9", empty: true };

  const t = avg > 0 ? Math.max(0, Math.min(1, (total - 0.8 * avg) / (0.4 * avg))) : 0.5;
  const L = GREEN_LIGHT - t * (GREEN_LIGHT - GREEN_DARK);
  const green = `hsl(96, 45%, ${L.toFixed(1)}%)`;
  const greenFg = L > 72 ? "#3B6D11" : "#1f3d08";

  if (nGrey === 0) return { background: green, fg: greenFg, empty: false };
  if (nGreen === 0) return { background: GREY, fg: GREY_FG, empty: false };

  const p = Math.round((nGreen / total) * 100);
  const lo = Math.max(0, p - 6);
  const hi = Math.min(100, p + 6);
  const background = `linear-gradient(to top right, ${green} 0%, ${green} ${lo}%, ${GREY} ${hi}%, ${GREY} 100%)`;
  return { background, fg: nGreen >= nGrey ? greenFg : GREY_FG, empty: false };
}
