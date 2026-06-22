import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
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
}

export default function CellDrawer({ clientId, subsectionId, onClose, layers }: Props) {
  const qc = useQueryClient();
  const facts = useQuery<Fact[]>({
    queryKey: ["facts", clientId, subsectionId],
    queryFn: () => api.cellFacts(clientId, subsectionId),
  });

  const subsection = layers
    ?.flatMap(L => L.subsections.map(s => ({ ...s, layer: L })))
    .find(s => s.id === subsectionId);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftFlag, setDraftFlag] = useState<Flag>("green");
  const [draftRationale, setDraftRationale] = useState("");

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

  const rejectFact = useMutation({
    mutationFn: (id: number) => api.rejectFact(id),
    onSuccess: invalidate,
  });
  const restoreFact = useMutation({
    mutationFn: (id: number) => api.restoreFact(id),
    onSuccess: invalidate,
  });

  // founder attribution: who (of the company's founders) this fact is from
  const entities = useQuery<Entity[]>({ queryKey: ["entities", clientId], queryFn: () => api.entities(clientId) });
  const founders = (entities.data ?? []).filter(e => e.kind === "founder");
  const setSpeaker = useMutation({
    mutationFn: ({ id, entityId }: { id: number; entityId: number | null }) => api.setFactSpeaker(id, entityId),
    onSuccess: invalidate,
  });

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

        {facts.data?.map(f => (
          <div key={f.id} className={`rounded border p-3 ${flagBg(f.flag)} ${flagBorder(f.flag)} ${f.state === "rejected" ? "opacity-60" : ""}`}>
            {editingId === f.id ? (
              <div className="space-y-2">
                <textarea
                  value={draftText}
                  onChange={e => setDraftText(e.target.value)}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]"
                />
                <textarea
                  value={draftRationale}
                  onChange={e => setDraftRationale(e.target.value)}
                  placeholder={draftFlag === "red"
                    ? "Concern: что именно проблема (обязательно для red)"
                    : "Rationale (опц.)"}
                  rows={3}
                  className={`w-full text-xs border rounded px-2 py-1.5 min-h-[3rem] resize-none ${
                    draftFlag === "red" && !draftRationale.trim()
                      ? "border-red-400" : "border-ink-line"
                  }`}
                />
                <div className="flex items-center gap-2">
                  <FlagPicker value={draftFlag} onChange={setDraftFlag} />
                  <button
                    onClick={() => patchFact.mutate({ id: f.id, text: draftText, flag: draftFlag, rationale: draftRationale })}
                    disabled={draftFlag === "red" && !draftRationale.trim()}
                    title={draftFlag === "red" && !draftRationale.trim() ? "Red facts require a rationale" : undefined}
                    className="text-xs px-3 py-1 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
                  >Save</button>
                  <button
                    onClick={() => setEditingId(null)}
                    className="text-xs px-3 py-1 hover:bg-slate-100 rounded text-ink-mute"
                  >Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-start gap-2 mb-1.5">
                  <FlagDot flag={f.flag} className="mt-1.5" />
                  <div className={`text-sm leading-snug whitespace-pre-wrap flex-1
                    ${f.state === "rejected" || f.verification === "refuted" ? "line-through text-ink-mute" : ""}`}>{f.text}</div>
                  <div className="flex items-center gap-1 shrink-0">
                    {f.state === "rejected" ? (
                      <button onClick={() => restoreFact.mutate(f.id)}
                        className="text-[11px] text-ink-mute hover:text-ink px-1.5 py-0.5 rounded hover:bg-white">вернуть</button>
                    ) : (
                      <button onClick={() => rejectFact.mutate(f.id)}
                        className="text-[11px] text-red-600 hover:text-red-800 px-1.5 py-0.5 rounded hover:bg-white">снять</button>
                    )}
                    <button
                      onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); setDraftRationale(f.rationale ?? ""); }}
                      className="text-[11px] text-ink-mute hover:text-ink px-1.5 py-0.5 rounded hover:bg-white"
                    >edit</button>
                    <button
                      onClick={() => { if (confirm("Delete this fact?")) deleteFact.mutate(f.id); }}
                      className="text-[11px] text-red-600 hover:text-red-800 px-1.5 py-0.5 rounded hover:bg-white"
                    >delete</button>
                  </div>
                </div>
                {f.verification && f.verification !== "unverified" && (
                  <div className="mb-1.5 flex items-center gap-1.5 flex-wrap">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide
                      ${f.verification === "verified" ? "bg-emerald-50 text-emerald-700"
                        : f.verification === "refuted" ? "bg-flag-red-bg text-flag-red"
                        : "bg-amber-50 text-amber-700"}`}>
                      {f.verification === "verified" ? "проверено" : f.verification === "refuted" ? "опровергнуто" : "под вопросом"}
                    </span>
                    {f.entity && <span className="text-[11px] font-mono text-ink-mute border border-ink-line rounded px-1.5">≠ {f.entity}</span>}
                    {f.verification_note && <span className="text-[11px] text-ink-mute">{f.verification_note}</span>}
                  </div>
                )}
                {founders.length > 0 && f.state !== "rejected" && (
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <span className="text-[11px] text-ink-mute" title="кто из фаундеров это говорит/чей факт">🗣</span>
                    <select
                      value={f.speaker_entity_id ?? ""}
                      onChange={e => setSpeaker.mutate({ id: f.id, entityId: e.target.value ? Number(e.target.value) : null })}
                      className={`text-[11px] border border-ink-line rounded px-1.5 py-0.5 bg-white max-w-[15rem]
                        ${f.speaker_entity_id ? "text-ink" : "text-ink-mute"}`}
                    >
                      <option value="">— кто говорит? —</option>
                      {founders.map(fo => <option key={fo.id} value={fo.id}>{fo.name}</option>)}
                    </select>
                  </div>
                )}
                {(f.n_sources ?? 1) > 1 && (
                  <div className="mb-1.5 text-[11px] text-emerald-700">✓ {f.n_sources} независимых источника</div>
                )}
                {f.flag === "red" && (
                  f.rationale
                    ? <div className="mt-2 text-xs border-l-2 pl-2 leading-snug border-flag-red/60 text-flag-red">
                        <span className="font-medium uppercase tracking-wide text-[10px] mr-1">concern:</span>
                        {f.rationale}
                      </div>
                    : <div className="mt-2 text-xs text-amber-600 italic">
                        ⚠ Concern: (не указано) — обновите факт через edit
                      </div>
                )}
                {f.flag === "grey" && f.rationale && (
                  <div className="mt-2 text-xs border-l-2 pl-2 leading-snug border-flag-grey/60 text-ink-mute">
                    <span className="font-medium uppercase tracking-wide text-[10px] mr-1">gap:</span>
                    {f.rationale}
                  </div>
                )}
                {f.evidence_snippet && (
                  <blockquote className="mt-2 text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug">
                    {f.evidence_snippet}
                  </blockquote>
                )}
                <SourceLine
                  client_id={clientId}
                  channel={f.source_channel}
                  source_url={f.source_url}
                  source_title={f.source_title}
                  source_archive_url={f.source_archive_url}
                  ingest_audit_id={f.ingest_audit_id}
                  ingest_kind={f.ingest_kind}
                  audio_sha={f.audio_sha}
                  timestamp_sec={f.snippet_start_sec ?? undefined}
                  captured_at={f.captured_at}
                  onOpenAudio={(sha, sec) => openAudio(f.id, sha, sec)}
                />
                {audioPanel?.factId === f.id && (
                  <div className="mt-2 border-t border-ink-line/60 pt-2">
                    <AudioSourcePanel
                      ref={audioRef}
                      clientId={clientId}
                      sha={audioPanel.sha}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        ))}
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
