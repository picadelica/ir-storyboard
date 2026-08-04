import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { EpisodeDigest } from "../types";

interface Props {
  clientId: string;
  url: string;
  speakerEntityId: number | null;
  /** По умолчанию блок раскрыт: его читают до разбора фактов. */
  defaultOpen?: boolean;
}

const KIND_LABEL: Record<string, string> = {
  shifted: "сдвиг",
  reversed: "развернулся",
  new: "новое",
  gone_quiet: "замолчал",
  rhetoric_drift: "иначе формулирует",
};

function tc(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function at(url: string, sec: number): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}t=${Math.max(0, Math.round(sec))}s`;
}

/** «Обзор» эпизода: о чём говорили и что сдвинулось с прошлых выступлений.
 *  Read-only: ничего не требует, ничего не ломает — можно не читать. */
export default function EpisodeOverview({ clientId, url, speakerEntityId, defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [building, setBuilding] = useState(false);
  const [note, setNote] = useState("");
  const started = useRef(false);

  const existing = useQuery<EpisodeDigest[]>({
    queryKey: ["episode-digest", clientId, url, speakerEntityId],
    queryFn: () => api.episodeDigests({ client_id: clientId, url, speaker_entity_id: speakerEntityId }),
    enabled: Boolean(clientId && url),
  });
  const [digest, setDigest] = useState<EpisodeDigest | null>(null);
  const current = digest ?? (existing.data ?? [])[0] ?? null;

  // Обзор собирается сам — расшифровка уже есть, повторно распознавать не нужно.
  useEffect(() => {
    if (started.current || !speakerEntityId || existing.isLoading) return;
    if ((existing.data ?? []).length > 0) return;
    started.current = true;
    setBuilding(true);
    api.buildEpisodeDigest({ client_id: clientId, url, speaker_entity_id: speakerEntityId })
      .then(res => {
        if (res.status === "ok" && res.digest) setDigest(res.digest);
        else if (res.status === "no_transcript") setNote("");
        else setNote(res.reason ?? "");
      })
      .catch((e: Error) => setNote(e.message))
      .finally(() => setBuilding(false));
  }, [clientId, url, speakerEntityId, existing.isLoading, existing.data]);

  if (!speakerEntityId) return null;          // не знаем, кто говорит — обзора нет
  if (!current && !building && !note) return null;

  const p = current?.payload;
  const comparison = p?.comparison;

  return (
    <div className="border border-ink-line rounded-lg bg-white">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left"
      >
        <span className="text-ink-mute text-xs">{open ? "▾" : "▸"}</span>
        <span className="text-sm font-medium">Обзор</span>
        <span className="text-xs text-ink-mute">
          {building ? "собираем…" : comparison?.text ? "есть сравнение с прошлыми выступлениями" : ""}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4">
          {building && !current && (
            <div className="text-sm text-ink-mute">
              Читаем расшифровку — это займёт около минуты. Разбирать факты можно уже сейчас.
            </div>
          )}
          {!building && !current && note && (
            <div className="text-sm text-ink-mute">{note}</div>
          )}

          {p && (
            <>
              {p.main_motif && (
                <div className="text-sm leading-relaxed text-slate-800">{p.main_motif}</div>
              )}

              {p.blocks.length > 0 && (
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1.5">
                    О чём говорили
                  </div>
                  <ul className="space-y-1.5">
                    {p.blocks.map((b, i) => (
                      <li key={i} className="text-sm flex gap-2">
                        <a href={at(url, b.start_sec)} target="_blank" rel="noreferrer"
                           className="font-mono text-[11px] text-blue-600 hover:underline shrink-0 mt-0.5">
                          {tc(b.start_sec)}
                        </a>
                        <span className="text-slate-700">
                          <span className="font-medium">{b.theme}</span>
                          {b.gist && <> — {b.gist}</>}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {p.key_moments.length > 0 && (
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1.5">
                    Ключевые моменты
                  </div>
                  <ul className="space-y-2">
                    {p.key_moments.map((m, i) => (
                      <li key={i} className="text-sm border-l-2 border-slate-200 pl-3">
                        <div className="text-slate-800">
                          «{m.quote}»
                          {m.unverified && (
                            <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded border border-flag-mixed/40 bg-flag-mixed-bg text-flag-mixed">
                              нет в расшифровке дословно
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-ink-mute mt-0.5">
                          <a href={at(url, m.timecode_sec)} target="_blank" rel="noreferrer"
                             className="font-mono text-blue-600 hover:underline">{tc(m.timecode_sec)}</a>
                          {m.note && <> · {m.note}</>}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {p.indirect.length > 0 && (
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1.5">
                    Между строк
                  </div>
                  <ul className="space-y-1 text-sm text-slate-700 list-disc pl-5">
                    {p.indirect.map((x, i) => <li key={i}>{x}</li>)}
                  </ul>
                </div>
              )}

              {comparison?.text && (
                <div className="border-t border-ink-line pt-3">
                  <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1.5">
                    Что изменилось с прошлых выступлений
                  </div>
                  <div className="text-sm text-slate-800 leading-relaxed">{comparison.text}</div>
                  {comparison.details.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs text-ink-mute cursor-pointer hover:text-ink">
                        по пунктам ({comparison.details.length})
                      </summary>
                      <ul className="mt-2 space-y-2">
                        {comparison.details.map((d, i) => (
                          <li key={i} className="text-xs border-l-2 border-slate-200 pl-3">
                            <span className="font-medium">{d.topic}</span>
                            <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">
                              {KIND_LABEL[d.kind] ?? d.kind}
                            </span>
                            {d.note && <div className="text-ink-mute mt-0.5">{d.note}</div>}
                            {d.was?.quote && (
                              <div className="text-slate-600 mt-0.5">
                                было{d.was.date ? ` (${d.was.date})` : ""}: «{d.was.quote}»
                              </div>
                            )}
                            {d.now?.quote && (
                              <div className="text-slate-600">
                                сейчас: «{d.now.quote}»{" "}
                                <a href={at(url, d.now.timecode_sec)} target="_blank" rel="noreferrer"
                                   className="font-mono text-blue-600 hover:underline">{tc(d.now.timecode_sec)}</a>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
