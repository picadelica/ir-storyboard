import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { LLMIngestEdit, LLMIngestPreview, LLMResolvedFact } from "../types";
import FlagDot from "./FlagDot";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

const AGENT_OPTIONS = [
  { value: "chatgpt-deep-research", label: "ChatGPT Deep Research" },
  { value: "claude", label: "Claude Research" },
  { value: "perplexity", label: "Perplexity" },
  { value: "gemini", label: "Gemini Deep Research" },
  { value: "unknown", label: "Unknown / Other" },
];

const CHANNEL_COLORS: Record<string, string> = {
  archival: "bg-blue-100 text-blue-800",
  online_interview: "bg-purple-100 text-purple-800",
  online_research: "bg-slate-100 text-slate-700",
  offline_interview: "bg-red-100 text-red-800",
};

const FLAG_COLORS: Record<string, string> = {
  green: "text-emerald-700 bg-emerald-50 border-emerald-200",
  red: "text-red-700 bg-red-50 border-red-200",
  grey: "text-slate-500 bg-slate-50 border-slate-200",
};

export default function IngestLLMReport({ clientId, onJumpToCell }: Props) {
  const [screen, setScreen] = useState<"upload" | "preview" | "done">("upload");
  const [preview, setPreview] = useState<LLMIngestPreview | null>(null);
  const [edits, setEdits] = useState<Record<number, LLMIngestEdit>>({});
  const [agentHint, setAgentHint] = useState("chatgpt-deep-research");
  const [expertEmail, setExpertEmail] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const history = useQuery({
    queryKey: ["llm-ingest-history", clientId],
    queryFn: () => api.llmIngestHistory(clientId),
  });

  const analyzeMut = useMutation({
    mutationFn: (file: File) => api.llmIngestPreview(clientId, file, agentHint),
    onSuccess: (data) => {
      setPreview(data);
      setEdits({});
      setScreen("preview");
    },
  });

  const commitMut = useMutation({
    mutationFn: () =>
      api.llmIngestCommit(
        clientId,
        preview!,
        Object.values(edits),
        expertEmail || "anonymous@example.com",
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      qc.invalidateQueries({ queryKey: ["llm-ingest-history", clientId] });
      setScreen("done");
    },
  });

  function handleFile(file: File | undefined) {
    if (!file) return;
    analyzeMut.mutate(file);
  }

  function setEdit(idx: number, action: "keep" | "drop" | "edit", extra?: Partial<LLMIngestEdit>) {
    setEdits(prev => ({
      ...prev,
      [idx]: { fact_idx: idx, action, ...extra },
    }));
  }

  function getAction(idx: number): "keep" | "drop" | "edit" {
    return edits[idx]?.action ?? "keep";
  }

  const keptCount = preview
    ? preview.facts.filter((_, i) => getAction(i) !== "drop").length
    : 0;

  // ── Upload screen ────────────────────────────────────────────────────────

  if (screen === "upload") {
    return (
      <div className="p-5 max-w-2xl space-y-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Ingest LLM Report</h2>
          {history.data && history.data.length > 0 && (
            <span className="text-xs text-ink-mute">
              {history.data.length} previous ingest{history.data.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Agent selector */}
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1.5">LLM Agent</label>
          <div className="flex flex-wrap gap-2">
            {AGENT_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setAgentHint(opt.value)}
                className={`px-3 py-1.5 text-xs rounded border transition ${
                  agentHint === opt.value
                    ? "bg-ink text-white border-ink"
                    : "border-ink-line text-ink-mute hover:border-ink hover:text-ink"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition ${
            dragOver ? "border-blue-400 bg-blue-50" : "border-ink-line hover:border-slate-400"
          }`}
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => {
            e.preventDefault();
            setDragOver(false);
            handleFile(e.dataTransfer.files[0]);
          }}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".docx,.md,.txt,.pdf"
            className="hidden"
            onChange={e => handleFile(e.target.files?.[0])}
          />
          {analyzeMut.isPending ? (
            <div className="text-sm text-ink-mute">Analysing document…</div>
          ) : (
            <>
              <div className="text-sm font-medium text-ink mb-1">
                Drop file here or click to browse
              </div>
              <div className="text-xs text-ink-mute">.docx · .md · .txt · .pdf</div>
            </>
          )}
        </div>

        {analyzeMut.isError && (
          <div className="text-sm text-red-600 bg-red-50 rounded p-3">
            {String(analyzeMut.error)}
          </div>
        )}

        {/* History table */}
        {history.data && history.data.length > 0 && (
          <div>
            <div className="text-xs font-medium text-ink-mute mb-2 uppercase tracking-wide">
              Previous ingests
            </div>
            <table className="w-full text-xs">
              <thead className="text-[10px] text-ink-mute uppercase">
                <tr>
                  <th className="text-left py-1 pr-3">Date</th>
                  <th className="text-left py-1 pr-3">Agent</th>
                  <th className="text-right py-1 pr-3">Facts</th>
                  <th className="text-right py-1">Greys</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map(row => (
                  <tr key={row.id} className="border-t border-ink-line">
                    <td className="py-1.5 pr-3 font-mono">
                      {new Date(row.confirmed_at).toLocaleDateString()}
                    </td>
                    <td className="py-1.5 pr-3">{row.agent ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{row.facts_committed}</td>
                    <td className="py-1.5 text-right">{row.greys_emitted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  // ── Done screen ──────────────────────────────────────────────────────────

  if (screen === "done" && commitMut.data) {
    const r = commitMut.data;
    return (
      <div className="p-5 max-w-2xl space-y-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="font-semibold text-emerald-800 mb-1">
            Saved to matrix
          </div>
          <div className="text-sm text-emerald-700">
            {r.committed_facts} fact{r.committed_facts !== 1 ? "s" : ""} ·{" "}
            {r.committed_sources} source{r.committed_sources !== 1 ? "s" : ""} ·{" "}
            {r.skipped_facts} skipped (already existed)
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => onJumpToCell(preview?.facts[0]?.subsection_id ?? "6.1")}
            className="px-4 py-2 text-sm bg-ink text-white rounded hover:bg-ink/90"
          >
            View in Matrix
          </button>
          <button
            onClick={() => { setScreen("upload"); setPreview(null); analyzeMut.reset(); commitMut.reset(); }}
            className="px-4 py-2 text-sm border border-ink-line rounded hover:bg-slate-50"
          >
            Ingest another
          </button>
        </div>
      </div>
    );
  }

  // ── Preview screen ───────────────────────────────────────────────────────

  if (!preview) return null;

  return (
    <div className="p-5 max-w-4xl space-y-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">Preview</h2>
          <div className="text-xs text-ink-mute mt-0.5">
            Agent: {preview.detected_agent ?? "unknown"} ·{" "}
            {preview.facts.length} facts · {preview.sources.length} sources
          </div>
        </div>
        <button
          onClick={() => { setScreen("upload"); analyzeMut.reset(); }}
          className="text-xs text-ink-mute hover:text-ink"
        >
          ← Back
        </button>
      </div>

      {/* Parser notes */}
      {preview.notes.length > 0 && (
        <details className="text-xs text-ink-mute">
          <summary className="cursor-pointer hover:text-ink">
            {preview.notes.length} parser note{preview.notes.length !== 1 ? "s" : ""}
          </summary>
          <ul className="mt-1 space-y-0.5 pl-3">
            {preview.notes.map((n, i) => <li key={i}>— {n}</li>)}
          </ul>
        </details>
      )}

      {/* Sources — only show those with a URL or title */}
      <div>
        {(() => {
          const usable = preview.sources.filter(s => s.canonical_url || s.title);
          const empty = preview.sources.length - usable.length;
          return (
            <>
              <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
                Sources ({usable.length}{empty > 0 ? ` + ${empty} without URL` : ""})
              </div>
              <div className="space-y-1">
                {usable.map(s => (
                  <div key={s.cite_id} className="flex items-start gap-2 text-xs py-1">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${CHANNEL_COLORS[s.channel] ?? "bg-slate-100"}`}>
                      {s.channel}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="truncate font-medium">{s.title || s.canonical_url}</div>
                      {s.canonical_url && (
                        <a href={`https://${s.canonical_url}`} target="_blank" rel="noopener noreferrer"
                          className="text-blue-600 hover:underline truncate block"
                          onClick={e => e.stopPropagation()}>
                          {s.canonical_url}
                        </a>
                      )}
                    </div>
                    <span className="text-ink-mute">{s.publisher}</span>
                  </div>
                ))}
              </div>
            </>
          );
        })()}
      </div>

      {/* Facts */}
      <div>
        <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
          Facts ({preview.facts.length})
        </div>
        <div className="space-y-2">
          {preview.facts.map((fact, idx) => (
            <FactCard
              key={idx}
              idx={idx}
              fact={fact}
              action={getAction(idx)}
              onAction={(action) => setEdit(idx, action)}
            />
          ))}
        </div>
      </div>

      {/* Expert email + commit */}
      <div className="sticky bottom-0 bg-white border-t border-ink-line pt-4 pb-2 space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="email"
            placeholder="your@email.com"
            value={expertEmail}
            onChange={e => setExpertEmail(e.target.value)}
            className="flex-1 text-sm border border-ink-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-ink"
          />
          <button
            onClick={() => commitMut.mutate()}
            disabled={keptCount === 0 || commitMut.isPending}
            className={`px-5 py-2 text-sm rounded font-medium transition ${
              keptCount === 0 || commitMut.isPending
                ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                : "bg-ink text-white hover:bg-ink/90"
            }`}
          >
            {commitMut.isPending
              ? "Saving…"
              : `Save ${keptCount} fact${keptCount !== 1 ? "s" : ""} to matrix`}
          </button>
        </div>
        {keptCount === 0 && (
          <div className="text-xs text-red-600">Drop all facts — nothing to commit</div>
        )}
        {commitMut.isError && (
          <div className="text-xs text-red-600">{String(commitMut.error)}</div>
        )}
      </div>
    </div>
  );
}

// ── FactCard ─────────────────────────────────────────────────────────────────

interface FactCardProps {
  idx: number;
  fact: LLMResolvedFact;
  action: "keep" | "drop" | "edit";
  onAction: (action: "keep" | "drop") => void;
}

function FactCard({ idx, fact, action, onAction }: FactCardProps) {
  const flagStyle = FLAG_COLORS[fact.flag] ?? FLAG_COLORS.grey;
  const dropped = action === "drop";

  return (
    <div className={`border rounded-lg p-3 text-sm transition ${
      dropped ? "opacity-40 bg-slate-50" : "bg-white"
    } ${flagStyle}`}>
      <div className="flex items-start gap-2">
        {/* Subsection badge */}
        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/60 border shrink-0 mt-0.5">
          L{fact.subsection_id}
        </span>

        {/* Flag dot */}
        <FlagDot flag={fact.flag} className="mt-1.5" />

        <div className="flex-1 min-w-0">
          <div className={`${dropped ? "line-through" : ""}`}>{fact.text}</div>
          {fact.flag === "red" && (
            fact.rationale
              ? <div className="mt-1 text-xs border-l-2 border-flag-red/60 text-flag-red pl-2 leading-snug">
                  <span className="font-medium uppercase tracking-wide text-[10px] mr-1">concern:</span>
                  {fact.rationale}
                </div>
              : <div className="mt-1 text-xs italic text-amber-600">⚠ Concern: (не указано)</div>
          )}
          {fact.flag === "grey" && fact.rationale && (
            <div className="mt-1 text-xs border-l-2 border-slate-300 text-ink-mute pl-2 leading-snug">
              <span className="font-medium uppercase tracking-wide text-[10px] mr-1">gap:</span>
              {fact.rationale}
            </div>
          )}
          {fact.evidence_snippet && (
            <div className="mt-1 text-xs text-ink-mute italic line-clamp-2">
              "{fact.evidence_snippet}"
            </div>
          )}
          {fact.needs_review && (
            <div className="mt-1 text-[10px] text-amber-600">
              needs review — snippet from paraphrase
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-1 shrink-0">
          {!dropped ? (
            <button
              onClick={() => onAction("drop")}
              className="text-[10px] px-2 py-0.5 border border-red-200 text-red-600 rounded hover:bg-red-50"
            >
              drop
            </button>
          ) : (
            <button
              onClick={() => onAction("keep")}
              className="text-[10px] px-2 py-0.5 border border-emerald-200 text-emerald-600 rounded hover:bg-emerald-50"
            >
              restore
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
