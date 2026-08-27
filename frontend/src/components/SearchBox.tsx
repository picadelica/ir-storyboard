import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { subsectionNameRu } from "../lib/matrixLabels";
import type { SearchHit } from "../types";
import FlagDot from "./FlagDot";
import { HintTarget } from "./Hint";

/** Поиск по фактам: в шапке — только иконка-лупа; по клику (или Cmd/Ctrl+K)
 *  открывается модалка с полем, переключателем охвата и результатами. */
export default function SearchBox({ clientId }: { clientId: string }) {
  const [open, setOpen] = useState(false);

  // глобальный хоткей Cmd/Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); }
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <HintTarget title="Поиск" body="Быстрый поиск по фактам. Горячая клавиша: ⌘K / Ctrl+K.">
        <button onClick={() => setOpen(true)} aria-label="Поиск"
          className="w-10 h-10 grid place-items-center rounded-xl border border-transparent text-ink-mute hover:text-ink hover:bg-[#f6f6f1] hover:border-ink-line transition">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.6" />
            <path d="M14 14l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </HintTarget>
      {open && <SearchModal clientId={clientId} onClose={() => setOpen(false)} />}
    </>
  );
}

function SearchModal({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const nav = useNavigate();
  const [raw, setRaw] = useState("");
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<"client" | "all">("client");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    const t = setTimeout(() => setQ(raw.trim()), 200);
    return () => clearTimeout(t);
  }, [raw]);

  const res = useQuery({
    queryKey: ["search", q, scope, scope === "client" ? clientId : "*"],
    queryFn: () => api.search(q, scope, clientId),
    enabled: q.length >= 2,
  });
  const hits = res.data?.results ?? [];

  const pick = (h: SearchHit) => {
    onClose();
    nav(`/clients/${h.client_id}/matrix?cell=${h.subsection_id}&fact=${h.fact_id}`);
  };

  return (
    <div className="fixed inset-0 z-[60] bg-black/30 flex items-start justify-center pt-24 px-4" onClick={onClose}>
      <div className="w-full max-w-xl bg-white rounded-2xl border border-ink-line shadow-xl overflow-hidden"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 border-b border-ink-line">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" className="text-ink-mute shrink-0">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.6" />
            <path d="M14 14l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <input ref={inputRef} value={raw} onChange={e => setRaw(e.target.value)}
            placeholder="Поиск фактов…"
            className="flex-1 py-4 text-sm outline-none placeholder:text-ink-mute/70" />
          <div className="flex items-center rounded-xl border border-ink-line overflow-hidden text-[11px] shrink-0 bg-[#f6f6f1]">
            <HintTarget title="Искать здесь" body="Искать только внутри текущей компании.">
              <button onClick={() => setScope("client")}
                className={`px-2.5 py-1.5 transition ${scope === "client" ? "bg-ink text-white font-semibold" : "text-ink-mute hover:text-ink hover:bg-white"}`}>эта</button>
            </HintTarget>
            <HintTarget title="Искать везде" body="Искать по всем компаниям в базе.">
              <button onClick={() => setScope("all")}
                className={`px-2.5 py-1.5 transition ${scope === "all" ? "bg-ink text-white font-semibold" : "text-ink-mute hover:text-ink hover:bg-white"}`}>все</button>
            </HintTarget>
          </div>
        </div>

        {q.length >= 2 && (
          <div className="max-h-[60vh] overflow-y-auto">
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
                  <button onClick={() => pick(h)} className="w-full text-left px-4 py-2.5 hover:bg-[#f6f6f1] transition">
                    <div className="flex items-center gap-1.5 text-[10px] text-ink-mute mb-0.5">
                      <FlagDot flag={h.flag} size={8} />
                      {scope === "all" && <span className="font-medium text-ink">{h.client_name}</span>}
                      {scope === "all" && <span>·</span>}
                      <span className="font-mono">{h.subsection_id}</span>
                      <span className="truncate">{subsectionNameRu(h.subsection_id, h.subsection_name)}</span>
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
