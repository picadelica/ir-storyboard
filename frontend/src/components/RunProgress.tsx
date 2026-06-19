import { useEffect, useState } from "react";

/** Seconds elapsed since `active` flipped to true; resets to 0 when it goes false. */
export function useElapsed(active: boolean): number {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    if (!active) return;
    setSec(0);
    const t = setInterval(() => setSec(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [active]);
  return sec;
}

/**
 * Indeterminate progress for a single long LLM call. We can't know real
 * percent, so the bar creeps toward ~92% over `expected` seconds and shows the
 * elapsed counter, so it's obvious the process is alive.
 */
export function RunProgress({ active, elapsed, label, expected = 60 }: {
  active: boolean; elapsed: number; label: string; expected?: number;
}) {
  if (!active) return null;
  const pct = Math.min(92, Math.round((elapsed / expected) * 90));
  return (
    <div className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs font-mono text-ink-mute tabular-nums">{elapsed}s</span>
      </div>
      <div className="h-1.5 bg-slate-200 rounded overflow-hidden">
        <div className="h-full bg-ink transition-all duration-1000 ease-linear" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[11px] text-ink-mute mt-1.5">
        Идёт запрос к LLM — обычно ~30–60 сек. Можно уйти на другую вкладку, результат не потеряется.
      </div>
    </div>
  );
}
