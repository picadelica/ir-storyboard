// Заливка ячейки матрицы/досье по объёму записей.
// 10 фиксированных ступеней из прототипа: чем больше записей в ячейке
// относительно верхней границы шкалы, тем насыщеннее цвет.
// Верхние 20% значений считаем плато: если максимум = 100, шкала строится
// от 0 до 80, а значения 80–100 получают самый насыщенный цвет.
// Используем именно ступени, а не плавную формулу, чтобы пользователь видел
// понятные состояния, а не «почти одинаковые» оттенки. Две самые светлые
// ступени оставлены в исходной палитре для истории, но исключены из активной
// шкалы: непустая ячейка должна заметно отличаться от пустой.

const STEP_PALETTE = [
  { bg: "hsl(78, 54%, 96%)", fg: "#7C8078" },
  { bg: "hsl(78, 58%, 92%)", fg: "#596A28" },
  { bg: "hsl(78, 61%, 88%)", fg: "#4D6120" },
  { bg: "hsl(78, 64%, 83%)", fg: "#415819" },
  { bg: "hsl(78, 67%, 77%)", fg: "#344D14" },
  { bg: "hsl(78, 70%, 71%)", fg: "#283F12" },
  { bg: "hsl(78, 73%, 64%)", fg: "#20221F" },
  { bg: "hsl(78, 76%, 57%)", fg: "#20221F" },
  { bg: "hsl(78, 79%, 50%)", fg: "#20221F" },
  { bg: "hsl(78, 82%, 44%)", fg: "#20221F" },
] as const;

const ACTIVE_PALETTE = STEP_PALETTE.slice(2);

// Максимальное число записей на ячейку — база для 10-ступенчатой шкалы.
export function recordMax(totals: number[]): number {
  const nz = totals.filter(t => t > 0);
  if (!nz.length) return 0;
  return Math.max(...nz);
}

export interface CellFill {
  background: string;   // CSS background — всегда сплошной цвет
  fg: string;           // читаемый цвет текста (название и цифра)
  greyShare: number;    // доля серых карточек 0..1 — для полоски пробелов
  empty: boolean;       // в ячейке нет записей
}

export function cellFill(nGreen: number, nGrey: number, maxRecords: number): CellFill {
  const total = nGreen + nGrey;
  if (total === 0) return { background: "transparent", fg: "#8B877C", greyShare: 0, empty: true };

  const greyShare = nGrey / total;
  const scaleMax = maxRecords > 0 ? maxRecords * 0.8 : 0;
  const ratio = scaleMax > 0 ? Math.max(0, Math.min(1, total / scaleMax)) : 0;
  const step = Math.max(0, Math.min(ACTIVE_PALETTE.length - 1, Math.ceil(ratio * ACTIVE_PALETTE.length) - 1));
  const { bg: background, fg } = ACTIVE_PALETTE[step];
  return { background, fg, greyShare, empty: false };
}
