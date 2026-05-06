import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import type { Channel, Fact, Flag, Layer } from "../types";

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

  const [showAdd, setShowAdd] = useState(false);
  const [newText, setNewText] = useState("");
  const [newFlag, setNewFlag] = useState<Flag>("green");
  const [newChannel, setNewChannel] = useState<Channel>("online_research");
  const [newSourceTitle, setNewSourceTitle] = useState("");
  const [newSourceUrl, setNewSourceUrl] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["facts", clientId, subsectionId] });
    qc.invalidateQueries({ queryKey: ["matrix", clientId] });
    qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    qc.invalidateQueries({ queryKey: ["punch", clientId] });
  };

  const addFact = useMutation({
    mutationFn: () => api.addFact(clientId, subsectionId, {
      text: newText, flag: newFlag, channel: newChannel,
      source_title: newSourceTitle, source_url: newSourceUrl, confidence: 1.0,
    }),
    onSuccess: () => {
      setShowAdd(false); setNewText(""); setNewSourceTitle(""); setNewSourceUrl("");
      invalidate();
    },
  });

  const patchFact = useMutation({
    mutationFn: ({ id, text, flag }: { id: number; text: string; flag: Flag }) =>
      api.patchFact(id, { text, flag }),
    onSuccess: () => { setEditingId(null); invalidate(); },
  });

  const deleteFact = useMutation({
    mutationFn: (id: number) => api.deleteFact(id),
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
          <div key={f.id} className={`rounded border p-3 ${flagBg(f.flag)} ${flagBorder(f.flag)}`}>
            {editingId === f.id ? (
              <div className="space-y-2">
                <textarea
                  value={draftText}
                  onChange={e => setDraftText(e.target.value)}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]"
                />
                <div className="flex items-center gap-2">
                  <FlagPicker value={draftFlag} onChange={setDraftFlag} />
                  <button
                    onClick={() => patchFact.mutate({ id: f.id, text: draftText, flag: draftFlag })}
                    className="text-xs px-3 py-1 bg-ink text-white rounded hover:bg-black"
                  >Save</button>
                  <button
                    onClick={() => setEditingId(null)}
                    className="text-xs px-3 py-1 hover:bg-slate-100 rounded text-ink-mute"
                  >Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-1.5">
                  <FlagBadge flag={f.flag} />
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); }}
                      className="text-[11px] text-ink-mute hover:text-ink px-1.5 py-0.5 rounded hover:bg-white"
                    >edit</button>
                    <button
                      onClick={() => { if (confirm("Delete this fact?")) deleteFact.mutate(f.id); }}
                      className="text-[11px] text-red-600 hover:text-red-800 px-1.5 py-0.5 rounded hover:bg-white"
                    >delete</button>
                  </div>
                </div>
                <div className="text-sm leading-snug whitespace-pre-wrap">{f.text}</div>
                <div className="text-[10px] text-ink-mute mt-2 flex items-center gap-2 font-mono">
                  {f.source_channel && (
                    <span className="px-1.5 py-0.5 bg-white border border-ink-line rounded">{f.source_channel}</span>
                  )}
                  {f.source_title && <span className="truncate">{f.source_title}</span>}
                  {f.source_url && (
                    <a href={f.source_url} target="_blank" rel="noreferrer"
                       className="text-blue-600 underline truncate">link</a>
                  )}
                  <span className="ml-auto">{(f.captured_at ?? "").slice(0, 10)}</span>
                </div>
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
              placeholder="Source URL (опц.)"
              value={newSourceUrl}
              onChange={e => setNewSourceUrl(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5"
            />
            {channelHint && (
              <div className="text-[11px] text-ink-mute">{channelHint}</div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => addFact.mutate()}
                disabled={!newText.trim() || addFact.isPending}
                className="text-sm px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
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

function FlagBadge({ flag }: { flag: Flag }) {
  const map = {
    green: { color: "bg-flag-green text-white", label: "GREEN" },
    red:   { color: "bg-flag-red text-white",   label: "RED" },
    grey:  { color: "bg-flag-grey text-white",  label: "GREY" },
  } as const;
  const m = map[flag];
  return <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${m.color}`}>{m.label}</span>;
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
