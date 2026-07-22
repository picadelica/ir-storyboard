import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { SearchHit } from "../types";
import FlagDot from "./FlagDot";

/** Глобальный поиск по фактам с переключателем охвата (эта компания / все).
 *  Результат ведёт в нужную ячейку (при необходимости — сменив компанию),
 *  открывает drawer и подсвечивает карточку через ?cell=&fact=. */
export default function SearchBox({ clientId }: { clientId: string }) {
  const nav = useNavigate();
  const [raw, setRaw] = useState("");
  const [q, setQ] = useState("");            // debounced
  const [scope, setScope] = useState<"client" | "all">("client");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setQ(raw.trim()), 220);
    return () => clearTimeout(t);
  }, [raw]);

  // закрытие по клику вне
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const res = useQuery({
    queryKey: ["search", q, scope, scope === "client" ? clientId : "*"],
    queryFn: () => api.search(q, scope, clientId),
    enabled: q.length >= 2,
  });

  const hits = res.data?.results ?? [];

  const pick = (h: SearchHit) => {
    setOpen(false);
    setRaw("");
    nav(`/clients/${h.client_id}/matrix?cell=${h.subsection_id}&fact=${h.fact_id}`);
  };

  return (
    <div ref={boxRef} className="relative">
      <div className="flex items-center rounded-lg border border-ink-line bg-white overflow-hidden text-xs">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" className="ml-2 text-ink-mute shrink-0">
          <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" />
          <path d="M14 14l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <input
          value={raw}
          onChange={e => { setRaw(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={e => { if (e.key === "Escape") { setOpen(false); (e.target as HTMLInputElement).blur(); } }}
          placeholder="Поиск фактов…"
          className="w-44 px-2 py-1.5 outline-none placeholder:text-ink-mute/70"
        />
        <div className="flex items-center border-l border-ink-line text-[11px] shrink-0">
          <button
            onClick={() => setScope("client")}
            className={`px-2 py-1.5 transition ${scope === "client" ? "bg-ink text-white" : "text-ink-mute hover:text-ink"}`}
            title="искать в текущей компании"
          >эта</button>
          <button
            onClick={() => setScope("all")}
            className={`px-2 py-1.5 transition ${scope === "all" ? "bg-ink text-white" : "text-ink-mute hover:text-ink"}`}
            title="искать по всем компаниям"
          >все</button>
        </div>
      </div>

      {open && q.length >= 2 && (
        <div className="absolute right-0 mt-1 w-[30rem] max-h-[70vh] overflow-y-auto rounded-lg border border-ink-line bg-white shadow-xl z-50">
          {res.isLoading && <div className="px-3 py-3 text-xs text-ink-mute">Ищу…</div>}
          {!res.isLoading && hits.length === 0 && (
            <div className="px-3 py-3 text-xs text-ink-mute">Ничего не найдено по «{q}».</div>
          )}
          {hits.length > 0 && (
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-ink-mute border-b border-ink-line/60">
              {hits.length}{hits.length === 60 ? "+" : ""} совпадений{scope === "all" ? " · по всем компаниям" : ""}
            </div>
          )}
          <ul className="divide-y divide-ink-line/60">
            {hits.map(h => (
              <li key={`${h.client_id}-${h.fact_id}`}>
                <button
                  onClick={() => pick(h)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-50 transition"
                >
                  <div className="flex items-center gap-1.5 text-[10px] text-ink-mute mb-0.5">
                    <FlagDot flag={h.flag} size={8} />
                    {scope === "all" && <span className="font-medium text-ink">{h.client_name}</span>}
                    {scope === "all" && <span>·</span>}
                    <span className="font-mono">{h.subsection_id}</span>
                    <span className="truncate">{h.subsection_name}</span>
                    {h.state === "review" && <span className="text-amber-700">· черновик</span>}
                  </div>
                  {h.title && <div className="text-[13px] font-semibold text-ink leading-tight">{highlight(h.title, q)}</div>}
                  <div className="text-xs text-ink-mute leading-snug line-clamp-2">{highlight(h.text, q)}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Подсветка совпадения (регистронезависимо, кириллица-безопасно). */
function highlight(text: string, q: string) {
  if (!q) return text;
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  const out: React.ReactNode[] = [];
  let i = 0, k = 0;
  while (i < text.length) {
    const at = lower.indexOf(needle, i);
    if (at === -1) { out.push(text.slice(i)); break; }
    if (at > i) out.push(text.slice(i, at));
    out.push(<mark key={k++} className="bg-amber-200/70 rounded-sm px-0.5">{text.slice(at, at + needle.length)}</mark>);
    i = at + needle.length;
  }
  return out;
}
