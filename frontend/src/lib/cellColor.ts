import type { CellSummary } from "../types";

export type CellMode =
  | "empty"     // no facts at all
  | "grey"      // only explicit grey-flagged facts
  | "green"     // only green
  | "red"       // only red
  | "mixed";    // green + red OR green + grey marked etc.

export function modeOf(c: CellSummary): CellMode {
  const g = c.n_green || 0, r = c.n_red || 0, gr = c.n_grey || 0;
  if (g === 0 && r === 0 && gr === 0) return "empty";
  if (g === 0 && r === 0) return "grey";
  if (r > 0 && g > 0) return "mixed";
  if (r > 0) return "red";
  if (g > 0 && gr > 0) return "mixed";   // partial coverage with explicit gaps
  return "green";
}

export const cellModeStyles: Record<CellMode, { bg: string; border: string; text: string; label: string }> = {
  empty: { bg: "bg-flag-empty-bg",  border: "border-flag-empty",  text: "text-slate-500",      label: "untouched" },
  grey:  { bg: "bg-flag-grey-bg",   border: "border-flag-grey",   text: "text-flag-grey",      label: "explicit gap" },
  green: { bg: "bg-flag-green-bg",  border: "border-flag-green",  text: "text-flag-green",     label: "covered" },
  red:   { bg: "bg-flag-red-bg",    border: "border-flag-red",    text: "text-flag-red",       label: "concern" },
  mixed: { bg: "bg-flag-mixed-bg",  border: "border-flag-mixed",  text: "text-flag-mixed",     label: "mixed" },
};
