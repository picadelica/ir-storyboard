import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Channel, Entity, Fact, Flag, Layer } from "../types";
import SourceLine from "./SourceLine";
import AudioSourcePanel, { type AudioSourceHandle } from "./AudioSourcePanel";
import FlagDot from "./FlagDot";

interface Props {
  clientId: string;
  subsectionId: string;
  onClose: () => void;
  layers?: Layer[];
  focusFactId?: number;   // из поиска: подсветить/раскрыть эту карточку
}

export default function CellDrawer({ clientId, subsectionId, onClose, layers, focusFactId }: Props) {
  const qc = useQueryClient();
  const facts = useQuery<Fact[]>({
    queryKey: ["facts", clientId, subsectionId],
    queryFn: () => api.cellFacts(clientId, subsectionId),
  });

  // роль: одобрять черновики может владелец данных / супер-админ (локально без auth — все)
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const canApprove = !me.data?.auth || !!me.data?.is_admin
    || (client.data?.owner_tid != null && me.data?.tid === client.data.owner_tid);

  const subsection = layers
    ?.flatMap(L => L.subsections.map(s => ({ ...s, layer: L })))
    .find(s => s.id === subsectionId);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftFlag, setDraftFlag] = useState<Flag>("green");
  const [draftRationale, setDraftRationale] = useState("");
  const [draftTitle, setDraftTitle] = useState("");

  // Audio source player: one open panel at a time, keyed by fact id.
  const [audioPanel, setAudioPanel] = useState<{ factId: number; sha: string } | null>(null);
  const audioRef = useRef<AudioSourceHandle | null>(null);

  const openAudio = (factId: number, sha: string, sec: number) => {
    if (audioPanel?.factId === factId) {
      // Already open for this fact — just seek.
      audioRef.current?.seek(sec);
    } else {
      setAudioPanel({ factId, sha });
      // Seek once the panel (and its <audio>) has mounted.
      setTimeout(() => audioRef.current?.seek(sec), 0);
    }
  };

  const [showAdd, setShowAdd] = useState(false);
  const [showHidden, setShowHidden] = useState(false);   // collapsible for merged-away cards
  const [expandedKids, setExpandedKids] = useState<Set<number>>(new Set());   // inline-раскрытые исходники под собранной карточкой
  const toggleKid = (id: number) => setExpandedKids(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const [infoIds, setInfoIds] = useState<Set<number>>(new Set());   // per-fact "info" footer open
  const toggleInfo = (id: number) => setInfoIds(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const InfoBtn = ({ id }: { id: number }) => (
    <button onClick={() => toggleInfo(id)} aria-label="Источник и детали"
      className={infoIds.has(id) ? "text-ink" : "text-ink-mute/50 hover:text-ink"}>
      <svg width="15" height="15" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7.3" stroke="currentColor" strokeWidth="1.3"/><path d="M10 9v4.2M10 6.4v.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
    </button>
  );
  const [newText, setNewText] = useState("");
  const [newFlag, setNewFlag] = useState<Flag>("green");
  const [newChannel, setNewChannel] = useState<Channel>("online_research");
  const [newSourceTitle, setNewSourceTitle] = useState("");
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newSnippet, setNewSnippet] = useState("");
  const [newRationale, setNewRationale] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["facts", clientId, subsectionId] });
    qc.invalidateQueries({ queryKey: ["matrix", clientId] });
    qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    qc.invalidateQueries({ queryKey: ["punch", clientId] });
  };

  const isOnlineChannel = (ch: Channel) =>
    ch === "online_research" || ch === "online_interview" || ch === "archival";
  const snippetRequired = isOnlineChannel(newChannel);
  const snippetValid = !snippetRequired || newSnippet.trim().length >= 20;

  const addFact = useMutation({
    mutationFn: () => api.addFact(clientId, subsectionId, {
      text: newText, flag: newFlag, channel: newChannel,
      source_title: newSourceTitle, source_url: newSourceUrl,
      evidence_snippet: newSnippet, confidence: 1.0,
      rationale: newRationale.trim() || undefined,
    }),
    onSuccess: () => {
      setShowAdd(false); setNewText(""); setNewSourceTitle("");
      setNewSourceUrl(""); setNewSnippet(""); setNewRationale("");
      invalidate();
    },
  });

  const patchFact = useMutation({
    mutationFn: ({ id, text, flag, rationale }: { id: number; text: string; flag: Flag; rationale: string }) =>
      api.patchFact(id, { text, flag, rationale: rationale.trim() || undefined }),
    onSuccess: () => { setEditingId(null); invalidate(); },
  });

  const deleteFact = useMutation({
    mutationFn: (id: number) => api.deleteFact(id),
    onSuccess: invalidate,
  });

  // перенос факта в другой раздел (подсекцию) — факт уходит из этой ячейки
  const moveFact = useMutation({
    mutationFn: ({ id, toSid }: { id: number; toSid: string }) => api.moveFact(id, toSid),
    onSuccess: () => {
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "facts" });
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
    },
  });

  const restoreFact = useMutation({
    mutationFn: (id: number) => api.restoreFact(id),
    onSuccess: invalidate,
  });

  // одобрить черновик контрибьютора → active (владелец/админ)
  const approveFact = useMutation({
    mutationFn: (id: number) => api.promoteFact(id),
    onSuccess: invalidate,
  });

  // founder attribution: who (of the company's founders) this fact is from
  const entities = useQuery<Entity[]>({ queryKey: ["entities", clientId], queryFn: () => api.entities(clientId) });
  const founders = (entities.data ?? []).filter(e => e.kind === "founder");
  const setSpeaker = useMutation({
    mutationFn: ({ id, entityId }: { id: number; entityId: number | null }) => api.setFactSpeaker(id, entityId),
    onSuccess: invalidate,
  });
  const setTitle = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) => api.setFactTitle(id, title),
    onSuccess: invalidate,
  });
  const setMustHave = useMutation({
    mutationFn: ({ id, source }: { id: number; source: "" | "client" | "expert" }) => api.setMustHave(id, source),
    onSuccess: invalidate,
  });

  // Фокус из поиска: доскроллить к карточке и подсветить; исходник — раскрыть.
  const focusedRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!focusFactId) { focusedRef.current = undefined; return; }
    if (!facts.data || focusedRef.current === focusFactId) return;
    const target = facts.data.find(f => f.id === focusFactId);
    if (!target) return;
    focusedRef.current = focusFactId;
    if (target.state === "rejected") setShowHidden(true);
    setInfoIds(s => new Set(s).add(focusFactId));
    setTimeout(() => {
      const el = document.getElementById(`fact-${focusFactId}`);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      el?.classList.add("ring-2", "ring-blue-400");
      setTimeout(() => el?.classList.remove("ring-2", "ring-blue-400"), 1600);
    }, 80);
  }, [focusFactId, facts.data]);

  const channelHint = subsection
    ? `Primary channels for L${subsection.layer.id}: ${subsection.layer.primary_channels.join(", ")}`
    : "";

  return (
    <aside className="fixed top-0 right-0 bottom-0 w-[28rem] bg-white border-l border-ink-line shadow-xl
                      flex flex-col z-30">
      <div className="px-4 py-3 border-b border-ink-line flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-mono text-ink-mute">Cell {subsectionId}</div>
          <h3 className="text-base font-semibold leading-tight">
            {subsection ? subsection.name : subsectionId}
          </h3>
          {subsection && (
            <div className="text-[11px] text-ink-mute mt-0.5">
              L{subsection.layer.id} {subsection.layer.name}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-ink-mute hover:text-ink rounded p-1 -mr-1"
          aria-label="close"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {facts.isLoading && <div className="text-sm text-ink-mute">Loading facts…</div>}

        {facts.data && facts.data.length === 0 && !showAdd && (
          <div className="text-sm text-ink-mute italic py-3">
            No facts yet in this cell. Use the channels noted on the right
            of the layer label to populate it.
          </div>
        )}

        {(() => {
          const all = facts.data ?? [];
          const active = all.filter(f => f.state !== "rejected");
          const hidden = all.filter(f => f.state === "rejected");
          const jumpTo = (id: number) => {
            setShowHidden(true);
            setTimeout(() => {
              const el = document.getElementById(`fact-${id}`);
              el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
              el?.classList.add("ring-2", "ring-blue-400");
              setTimeout(() => el?.classList.remove("ring-2", "ring-blue-400"), 1200);
            }, 60);
          };
          return (<>
            {active.map(f => {
              const kids = hidden.filter(h => h.merged_into === f.id);
              return (
                <div key={f.id} id={`fact-${f.id}`} className={`rounded-lg border p-3 transition-shadow ${flagBg(f.flag)} ${flagBorder(f.flag)}`}>
                  {editingId === f.id ? (
                    <div className="space-y-2">
                      <input value={draftTitle} onChange={e => setDraftTitle(e.target.value)}
                        placeholder="Заголовок (2-3 слова)"
                        className="w-full text-sm font-semibold border border-ink-line rounded px-2 py-1.5" />
                      <textarea value={draftText} onChange={e => setDraftText(e.target.value)}
                        className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]" />
                      <textarea value={draftRationale} onChange={e => setDraftRationale(e.target.value)}
                        placeholder={draftFlag === "red" ? "Concern: что именно проблема (обязательно для red)" : "Rationale (опц.)"}
                        rows={3}
                        className={`w-full text-xs border rounded px-2 py-1.5 min-h-[3rem] resize-none ${draftFlag === "red" && !draftRationale.trim() ? "border-red-400" : "border-ink-line"}`} />
                      <div className="flex items-center gap-2">
                        <FlagPicker value={draftFlag} onChange={setDraftFlag} />
                        <button onClick={() => {
                            patchFact.mutate({ id: f.id, text: draftText, flag: draftFlag, rationale: draftRationale });
                            if ((draftTitle ?? "") !== (f.title ?? "")) setTitle.mutate({ id: f.id, title: draftTitle });
                          }}
                          disabled={draftFlag === "red" && !draftRationale.trim()}
                          className="text-xs px-3 py-1 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">Save</button>
                        <button onClick={() => setEditingId(null)} className="text-xs px-3 py-1 hover:bg-slate-100 rounded text-ink-mute">Cancel</button>
                      </div>
                      {/* перенос в другой раздел (подсекцию) — факт уходит из этой ячейки */}
                      <div className="flex items-center gap-2 pt-1 border-t border-ink-line/60">
                        <span className="text-xs text-ink-mute" title="перенести факт в другой раздел матрицы">Раздел:</span>
                        <select value={subsectionId} disabled={moveFact.isPending}
                          onChange={e => {
                            const to = e.target.value;
                            if (to && to !== subsectionId) { moveFact.mutate({ id: f.id, toSid: to }); setEditingId(null); }
                          }}
                          className="text-xs border border-ink-line rounded px-1.5 py-1 bg-white max-w-[18rem]">
                          {(layers ?? []).map(L => (
                            <optgroup key={L.id} label={`L${L.id}. ${L.name}`}>
                              {L.subsections.map(s => <option key={s.id} value={s.id}>{s.id} {s.name}</option>)}
                            </optgroup>
                          ))}
                        </select>
                        {moveFact.isPending && <span className="text-[11px] text-ink-mute">переношу…</span>}
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* top row: flag + star (left), edit + delete (right) */}
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-3">
                          <FlagDot flag={f.flag} size={11} />
                          {(() => {
                            const by = f.must_have_by || (f.must_have ? "client" : "");
                            const next = by === "" ? "client" : by === "client" ? "expert" : "";
                            const color = by === "client" ? "text-flag-blue" : by === "expert" ? "text-purple-600" : "text-ink-mute/40 hover:text-flag-blue";
                            const title = by === "client" ? "must-have от клиента (обязательно) → клик: от эксперта"
                              : by === "expert" ? "важное от эксперта (приоритет) → клик: снять"
                              : "клик: must-have от клиента (синяя)";
                            return <button onClick={() => setMustHave.mutate({ id: f.id, source: next as "" | "client" | "expert" })}
                              title={title} className={`text-[15px] leading-none ${color}`}>★</button>;
                          })()}
                          <InfoBtn id={f.id} />
                          {f.state === "review" && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide bg-amber-100 text-amber-800"
                              title="черновик — ждёт одобрения владельца данных">черновик</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-ink-mute">
                          {f.state === "review" && canApprove && (
                            <button onClick={() => approveFact.mutate(f.id)} disabled={approveFact.isPending}
                              className="text-[11px] px-2 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300"
                              title="одобрить черновик — попадёт в матрицу">одобрить</button>
                          )}
                          <button onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); setDraftRationale(f.rationale ?? ""); setDraftTitle(f.title ?? ""); }}
                            aria-label="Редактировать" className="hover:text-ink">
                            <svg width="16" height="16" viewBox="0 0 20 20" fill="none"><path d="M4 13.5V16h2.5l7.4-7.4-2.5-2.5L4 13.5zM13.1 4.9l2.5 2.5 1-1a1.4 1.4 0 0 0-2-2l-1.5.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>
                          </button>
                          <button onClick={() => { if (confirm("Удалить факт безвозвратно?")) deleteFact.mutate(f.id); }}
                            aria-label="Удалить" className="hover:text-flag-red">
                            <svg width="16" height="16" viewBox="0 0 20 20" fill="none"><path d="M4 6h12M8 6V4.5h4V6M6.5 6l.7 9.5h5.6L13.5 6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
                          </button>
                        </div>
                      </div>

                      {/* title (bold, slightly larger) + fact text (justified to fill) */}
                      {f.title && <div className="text-[15px] font-semibold text-ink leading-tight mb-0.5">{f.title}</div>}
                      <div className="text-sm leading-snug whitespace-pre-wrap text-ink" style={{ textAlign: "justify" }}>{f.text}</div>

                      {/* speaker — kept in the text body */}
                      {founders.length > 0 && (
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <span className="text-[11px] text-ink-mute" title="кто из фаундеров это говорит/чей факт">🗣</span>
                          <select value={f.speaker_entity_id ?? ""}
                            onChange={e => setSpeaker.mutate({ id: f.id, entityId: e.target.value ? Number(e.target.value) : null })}
                            className={`text-[11px] border border-ink-line rounded px-1.5 py-0.5 bg-white max-w-[15rem] ${f.speaker_entity_id ? "text-ink" : "text-ink-mute"}`}>
                            <option value="">— кто говорит? —</option>
                            {founders.map(fo => <option key={fo.id} value={fo.id}>{fo.name}</option>)}
                          </select>
                        </div>
                      )}

                      {/* risk / gap — kept in the text body */}
                      {f.flag === "red" && (f.rationale
                        ? <div className="mt-1.5 text-xs border-l-2 pl-2 leading-snug border-flag-red/60 text-flag-red">
                            <span className="font-medium uppercase tracking-wide text-[10px] mr-1">риск:</span>{f.rationale}</div>
                        : <div className="mt-1.5 text-xs text-amber-600 italic">⚠ риск не указан — добавьте через edit</div>)}
                      {f.flag === "grey" && f.rationale && (
                        <div className="mt-1.5 text-xs border-l-2 pl-2 leading-snug border-flag-grey/60 text-ink-mute">
                          <span className="font-medium uppercase tracking-wide text-[10px] mr-1">gap:</span>{f.rationale}</div>)}

                      {/* verification (only when meaningful) */}
                      {f.verification && f.verification !== "unverified" && (
                        <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${f.verification === "verified" ? "bg-emerald-50 text-emerald-700" : f.verification === "refuted" ? "bg-flag-red-bg text-flag-red" : "bg-amber-50 text-amber-700"}`}>
                            {f.verification === "verified" ? "проверено" : f.verification === "refuted" ? "опровергнуто" : "под вопросом"}</span>
                          {f.entity && <span className="text-[11px] font-mono text-ink-mute border border-ink-line rounded px-1.5">≠ {f.entity}</span>}
                        </div>
                      )}

                      {/* провенанс: кто внёс/собрал · кто подтвердил · когда.
                          Сентинелы пайплайна (merge/attribute/…) — не пользователи, не показываем как автора. */}
                      {(() => {
                        const SENT = new Set(["merge", "attribute", "dev", "stub", "import", "seed", ""]);
                        const isJoint = kids.length > 0 || f.created_by === "merge" || !!f.merged_by;
                        const author = isJoint
                          ? (f.merged_by && !SENT.has(f.merged_by) ? `собрал ${f.merged_by}` : "собрано")
                          : (f.created_by && !SENT.has(f.created_by) ? `внёс ${f.created_by}` : "");
                        const parts: string[] = [];
                        if (author) parts.push(author);
                        if (f.approved_by) parts.push(`подтвердил ${f.approved_by}`);
                        if (f.captured_at) parts.push(f.captured_at.slice(0, 10));
                        if (!parts.length) return null;
                        return (
                          <div className="mt-1.5 text-[10px] text-ink-mute/70 flex flex-wrap gap-x-2 gap-y-0.5">
                            {parts.map((p, i) => <span key={i}>{i ? "· " : ""}{p}</span>)}
                          </div>
                        );
                      })()}

                      {/* footer (source + merged-from links) — collapsed behind the info icon */}
                      {infoIds.has(f.id) && (
                        <div className="mt-2 pt-2 border-t border-ink-line/60">
                          {kids.length > 0 && (() => {
                            // Два режима склейки:
                            //  • curated (created_by='merge') — это НОВАЯ синтез-карточка, собранная из kids
                            //    оригиналов; сама она не оригинал → «собрано из kids», без чипа «эта».
                            //  • default-keep — видимая карточка сама один из оригиналов (+ kids дублей)
                            //    → «собрано из kids+1», первый чип «#id · эта».
                            const curated = f.created_by === "merge";
                            const total = curated ? kids.length : kids.length + 1;
                            const nounForm = total === 1 ? "карточки" : "карточек";
                            return (
                            <div className="mb-1">
                              <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-mute">
                                <span>собрано из {total} {nounForm}:</span>
                                {/* сама эта карточка — один из оригиналов (не ссылка), чтобы число совпадало с чипами */}
                                {!curated && (
                                  <span title="эта карточка — канонический вариант"
                                    className="font-mono px-1.5 py-0.5 rounded border border-emerald-200 bg-emerald-50 text-emerald-700">
                                    #{f.id} · эта
                                  </span>
                                )}
                                {kids.map(k => {
                                  const open = expandedKids.has(k.id);
                                  return (
                                    <button key={k.id} onClick={() => toggleKid(k.id)} title={k.text}
                                      className={`font-mono px-1.5 py-0.5 rounded border text-blue-600 hover:bg-blue-50 ${open ? "border-blue-300 bg-blue-50" : "border-ink-line"}`}>
                                      {open ? "▾" : "▸"} #{k.id}
                                    </button>
                                  );
                                })}
                              </div>
                              {/* исходники раскрываются тут же, без прыжка вниз */}
                              {kids.some(k => expandedKids.has(k.id)) && (
                                <div className="mt-1.5 space-y-1.5">
                                  {kids.filter(k => expandedKids.has(k.id)).map(k => (
                                    <div key={k.id} className="rounded border border-ink-line bg-slate-50/70 p-2">
                                      <div className="flex items-center gap-1.5 text-[10px] text-ink-mute mb-1">
                                        <FlagDot flag={k.flag} size={9} />
                                        <span>исходная #{k.id}</span>
                                        <button onClick={() => restoreFact.mutate(k.id)}
                                          className="ml-auto text-ink-mute hover:text-ink" title="вернуть в матрицу как отдельную карточку">вернуть</button>
                                      </div>
                                      {k.title && <div className="text-xs font-semibold text-ink-mute leading-tight">{k.title}</div>}
                                      <div className="text-xs leading-snug whitespace-pre-wrap text-ink-mute" style={{ textAlign: "justify" }}>{k.text}</div>
                                      {k.evidence_snippet && (
                                        <blockquote className="mt-1 text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug">{k.evidence_snippet}</blockquote>
                                      )}
                                      <SourceLine client_id={clientId} channel={k.source_channel} source_url={k.source_url}
                                        source_title={k.source_title} source_archive_url={k.source_archive_url}
                                        ingest_audit_id={k.ingest_audit_id} ingest_kind={k.ingest_kind} audio_sha={k.audio_sha}
                                        timestamp_sec={k.snippet_start_sec ?? undefined} captured_at={k.captured_at}
                                        onOpenAudio={(sha, sec) => openAudio(k.id, sha, sec)} />
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                            );
                          })()}
                          {/* собранная карточка несёт ТОЛЬКО ссылки на исходные — цитата/источник живут в исходных */}
                          {kids.length === 0 && (<>
                            {f.evidence_snippet && (
                              <blockquote className="text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug mb-1">{f.evidence_snippet}</blockquote>
                            )}
                            <SourceLine client_id={clientId} channel={f.source_channel} source_url={f.source_url}
                              source_title={f.source_title} source_archive_url={f.source_archive_url}
                              ingest_audit_id={f.ingest_audit_id} ingest_kind={f.ingest_kind} audio_sha={f.audio_sha}
                              timestamp_sec={f.snippet_start_sec ?? undefined} captured_at={f.captured_at}
                              onOpenAudio={(sha, sec) => openAudio(f.id, sha, sec)} />
                            {audioPanel?.factId === f.id && (
                              <div className="mt-2 border-t border-ink-line/60 pt-2">
                                <AudioSourcePanel ref={audioRef} clientId={clientId} sha={audioPanel.sha} />
                              </div>
                            )}
                          </>)}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}

            {/* merged-away originals under a collapsible (each keeps its own source) */}
            {hidden.length > 0 && (
              <details open={showHidden} onToggle={e => setShowHidden((e.currentTarget as HTMLDetailsElement).open)}
                className="rounded-lg border border-dashed border-ink-line p-2">
                <summary className="text-[11px] text-ink-mute cursor-pointer list-none">
                  показать {hidden.length} исходных карточек
                </summary>
                <div className="mt-2 space-y-2">
                  {hidden.map(h => (
                    <div key={h.id} id={`fact-${h.id}`} className="rounded border border-ink-line bg-slate-50/60 p-2.5 transition-shadow">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="flex items-center gap-2 text-[10px] text-ink-mute">
                          <FlagDot flag={h.flag} size={9} />
                          <span className="px-1.5 py-0.5 rounded bg-slate-200/70">
                            исходная{h.merged_into ? ` · в #${h.merged_into}` : ""}
                          </span>
                        </span>
                        <span className="flex items-center gap-2 shrink-0">
                          {h.merged_into && (
                            <button onClick={() => jumpTo(h.merged_into!)} className="text-[11px] text-blue-600 hover:underline">↑ к общей #{h.merged_into}</button>
                          )}
                          <button onClick={() => restoreFact.mutate(h.id)} className="text-[11px] text-ink-mute hover:text-ink">вернуть</button>
                        </span>
                      </div>
                      {h.title && <div className="text-xs font-semibold text-ink-mute leading-tight">{h.title}</div>}
                      <div className="text-xs leading-snug whitespace-pre-wrap text-ink-mute" style={{ textAlign: "justify" }}>{h.text}</div>
                      {/* originals keep their own provenance — always shown here */}
                      <div className="mt-1.5 pt-1.5 border-t border-ink-line/60">
                        {h.evidence_snippet && (
                          <blockquote className="text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug mb-1">{h.evidence_snippet}</blockquote>
                        )}
                        <SourceLine client_id={clientId} channel={h.source_channel} source_url={h.source_url}
                          source_title={h.source_title} source_archive_url={h.source_archive_url}
                          ingest_audit_id={h.ingest_audit_id} ingest_kind={h.ingest_kind} audio_sha={h.audio_sha}
                          timestamp_sec={h.snippet_start_sec ?? undefined} captured_at={h.captured_at}
                          onOpenAudio={(sha, sec) => openAudio(h.id, sha, sec)} />
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </>);
        })()}
      </div>

      <div className="border-t border-ink-line p-4 bg-slate-50">
        {!showAdd ? (
          <button
            onClick={() => setShowAdd(true)}
            className="w-full text-sm px-3 py-2 bg-ink text-white rounded hover:bg-black"
          >+ Добавить факт</button>
        ) : (
          <div className="space-y-2">
            <textarea
              placeholder="Текст факта"
              value={newText}
              onChange={e => setNewText(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]"
            />
            <div className="grid grid-cols-2 gap-2">
              <FlagPicker value={newFlag} onChange={setNewFlag} />
              <select
                value={newChannel}
                onChange={e => setNewChannel(e.target.value as Channel)}
                className="text-sm border border-ink-line rounded px-2 py-1.5"
              >
                <option value="online_research">online_research</option>
                <option value="online_interview">online_interview</option>
                <option value="archival">archival</option>
                <option value="offline_interview">offline_interview</option>
              </select>
            </div>
            <input
              placeholder="Source title (опц.)"
              value={newSourceTitle}
              onChange={e => setNewSourceTitle(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5"
            />
            <input
              placeholder={snippetRequired ? "Source URL (обязательно для online/archival)" : "Source URL (опц.)"}
              value={newSourceUrl}
              onChange={e => setNewSourceUrl(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5"
            />
            <div>
              <textarea
                placeholder={snippetRequired
                  ? "Цитата из источника ≥20 символов (обязательно)"
                  : "Цитата из источника (опц.)"}
                value={newSnippet}
                onChange={e => setNewSnippet(e.target.value)}
                rows={3}
                className={`w-full text-sm border rounded px-2 py-1.5 resize-none
                  ${snippetRequired && newSnippet.trim().length > 0 && !snippetValid
                    ? "border-red-400" : "border-ink-line"}`}
              />
              {snippetRequired && (
                <div className={`text-[10px] mt-0.5 ${snippetValid ? "text-ink-mute" : "text-red-500"}`}>
                  {newSnippet.trim().length}/20 chars required
                </div>
              )}
            </div>
            <textarea
              placeholder={newFlag === "red"
                ? "Concern: что именно проблема (обязательно для red)"
                : "Rationale (опц.)"}
              value={newRationale}
              onChange={e => setNewRationale(e.target.value)}
              rows={2}
              className={`w-full text-xs border rounded px-2 py-1.5 resize-none ${
                newFlag === "red" && !newRationale.trim() && newText
                  ? "border-red-400" : "border-ink-line"
              }`}
            />
            {channelHint && (
              <div className="text-[11px] text-ink-mute">{channelHint}</div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => addFact.mutate()}
                disabled={!newText.trim() || !snippetValid || (newFlag === "red" && !newRationale.trim()) || addFact.isPending}
                className="text-sm px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
                title={
                  !snippetValid ? "Evidence snippet ≥20 chars required for online channels"
                  : (newFlag === "red" && !newRationale.trim()) ? "Red facts require a rationale"
                  : undefined
                }
              >Save</button>
              <button
                onClick={() => setShowAdd(false)}
                className="text-sm px-3 py-1.5 hover:bg-slate-200 rounded text-ink-mute"
              >Cancel</button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function flagBg(f: Flag) {
  return f === "green" ? "bg-flag-green-bg" : f === "red" ? "bg-flag-red-bg" : "bg-flag-grey-bg";
}
function flagBorder(f: Flag) {
  return f === "green" ? "border-flag-green/40" : f === "red" ? "border-flag-red/40" : "border-flag-grey/40";
}

function FlagPicker({ value, onChange }: { value: Flag; onChange: (f: Flag) => void }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value as Flag)}
      className="text-sm border border-ink-line rounded px-2 py-1.5"
    >
      <option value="green">green</option>
      <option value="red">red</option>
      <option value="grey">grey (gap)</option>
    </select>
  );
}
