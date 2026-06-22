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

type PdfCand = { text: string; subsection_id: string; subsection_name: string; flag: string; rationale: string };

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

  // ── "Промпт + ответ" mode: generate a deep-research prompt, run it externally,
  // paste the answer back (parsed by the same pipeline as an uploaded file).
  const [mode, setMode] = useState<"file" | "prompt" | "pdf">("file");
  const [promptAgent, setPromptAgent] = useState("chatgpt");
  const [promptText, setPromptText] = useState("");
  const [answer, setAnswer] = useState("");
  const [copied, setCopied] = useState(false);

  const genPrompt = useMutation({
    mutationFn: () => api.llmReportPrompt(clientId, promptAgent),
    onSuccess: (r) => setPromptText(r.prompt),
  });
  const analyzeText = useMutation({
    mutationFn: () => api.llmIngestPreviewText(clientId, answer,
      promptAgent === "chatgpt" ? "chatgpt-deep-research" : promptAgent),
    onSuccess: (data) => { setPreview(data); setEdits({}); setScreen("preview"); },
  });
  const copyPrompt = async () => {
    try { await navigator.clipboard.writeText(promptText); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  const PROMPT_AGENTS = [
    { value: "chatgpt", label: "ChatGPT Deep Research" }, { value: "claude", label: "Claude" },
    { value: "perplexity", label: "Perplexity" }, { value: "gemini", label: "Gemini" },
  ];

  // ── "Произвольный PDF" mode: Claude vision reads any PDF (incl. scanned) →
  // facts mapped to the matrix → analyst picks → committed as archival.
  const pdfRef = useRef<HTMLInputElement>(null);
  const [pdfTitle, setPdfTitle] = useState("");
  const [pdfCands, setPdfCands] = useState<PdfCand[] | null>(null);
  const [pdfAccepted, setPdfAccepted] = useState<Set<number>>(new Set());
  const pdfPreviewMut = useMutation({
    mutationFn: (file: File) => api.otherPdfPreview(clientId, file),
    onSuccess: (r) => {
      setPdfTitle(r.source_title || "Документ");
      const cands: PdfCand[] = r.candidates.map(c => ({
        text: c.text, subsection_id: c.suggested_subsection_id || "",
        subsection_name: c.suggested_subsection_name, flag: c.suggested_flag, rationale: c.rationale || "",
      }));
      setPdfCands(cands);
      setPdfAccepted(new Set(cands.map((_, i) => i)));
    },
  });
  const pdfCommitMut = useMutation({
    mutationFn: () => api.otherPdfCommit(clientId, pdfTitle,
      (pdfCands ?? []).filter((_, i) => pdfAccepted.has(i)).map(c => ({
        text: c.text, subsection_id: c.subsection_id, flag: c.flag, rationale: c.rationale || undefined,
      }))),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      setPdfCands(null); setPdfAccepted(new Set());
    },
  });
  const togglePdf = (i: number) => setPdfAccepted(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });

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

        {/* mode toggle */}
        <div className="inline-flex rounded-lg border border-ink-line overflow-hidden text-sm">
          <button onClick={() => setMode("file")}
            className={`px-3.5 py-1.5 ${mode === "file" ? "bg-ink text-white" : "text-ink-mute hover:bg-ink/[0.04]"}`}>Файл</button>
          <button onClick={() => setMode("prompt")}
            className={`px-3.5 py-1.5 ${mode === "prompt" ? "bg-ink text-white" : "text-ink-mute hover:bg-ink/[0.04]"}`}>Промпт + ответ</button>
          <button onClick={() => setMode("pdf")}
            className={`px-3.5 py-1.5 ${mode === "pdf" ? "bg-ink text-white" : "text-ink-mute hover:bg-ink/[0.04]"}`}>Произвольный PDF</button>
        </div>

        {mode === "file" && (
          <>
            {/* Agent selector */}
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1.5">LLM Agent</label>
              <div className="flex flex-wrap gap-2">
                {AGENT_OPTIONS.map(opt => (
                  <button key={opt.value} onClick={() => setAgentHint(opt.value)}
                    className={`px-3 py-1.5 text-xs rounded border transition ${
                      agentHint === opt.value ? "bg-ink text-white border-ink"
                        : "border-ink-line text-ink-mute hover:border-ink hover:text-ink"}`}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Drop zone */}
            <div
              className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition ${
                dragOver ? "border-blue-400 bg-blue-50" : "border-ink-line hover:border-slate-400"}`}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
              onClick={() => fileRef.current?.click()}
            >
              <input ref={fileRef} type="file" accept=".docx,.md,.txt,.pdf" className="hidden"
                onChange={e => handleFile(e.target.files?.[0])} />
              {analyzeMut.isPending ? (
                <div className="text-sm text-ink-mute">Analysing document…</div>
              ) : (
                <>
                  <div className="text-sm font-medium text-ink mb-1">Drop file here or click to browse</div>
                  <div className="text-xs text-ink-mute">.docx · .md · .txt · .pdf</div>
                </>
              )}
            </div>
            {analyzeMut.isError && (
              <div className="text-sm text-red-600 bg-red-50 rounded p-3">{String(analyzeMut.error)}</div>
            )}
          </>
        )}

        {mode === "prompt" && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <label className="text-xs text-ink-mute">Агент</label>
              <select value={promptAgent} onChange={e => setPromptAgent(e.target.value)}
                className="text-xs border border-ink-line rounded px-2 py-1 bg-white">
                {PROMPT_AGENTS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
              <button onClick={() => genPrompt.mutate()} disabled={genPrompt.isPending}
                className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">
                {genPrompt.isPending ? "…" : "Сгенерировать промпт"}
              </button>
            </div>

            {promptText && (
              <div className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-medium text-ink-mute">1. Скопируй промпт в {PROMPT_AGENTS.find(a => a.value === promptAgent)?.label}</span>
                  <button onClick={copyPrompt} className="text-[11px] text-blue-600 hover:underline">{copied ? "Скопировано ✓" : "Copy"}</button>
                </div>
                <textarea readOnly value={promptText} rows={8}
                  className="w-full text-xs font-mono border border-ink-line rounded px-2.5 py-2 bg-slate-50 leading-relaxed" />
              </div>
            )}

            <div className="space-y-1.5">
              <span className="text-xs font-medium text-ink-mute">2. Вставь ответ агента и разбери</span>
              <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={10}
                placeholder="Вставь сюда текст ответа deep-research (с источниками [N] в конце)…"
                className="w-full text-sm border border-ink-line rounded px-2.5 py-2 leading-relaxed" />
              <div className="flex items-center gap-2">
                <button onClick={() => analyzeText.mutate()} disabled={analyzeText.isPending || !answer.trim()}
                  className="text-sm px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                  {analyzeText.isPending ? "Разбираю…" : "Разобрать ответ"}
                </button>
                {analyzeText.isError && <span className="text-xs text-red-600">{String(analyzeText.error)}</span>}
              </div>
            </div>
          </div>
        )}

        {mode === "pdf" && (
          <div className="space-y-3">
            {!pdfCands && (
              <div
                className="border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition border-ink-line hover:border-slate-400"
                onClick={() => pdfRef.current?.click()}
                onDragOver={e => e.preventDefault()}
                onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) pdfPreviewMut.mutate(f); }}
              >
                <input ref={pdfRef} type="file" accept=".pdf" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) pdfPreviewMut.mutate(f); }} />
                {pdfPreviewMut.isPending ? (
                  <div className="text-sm text-ink-mute">Распознаю PDF и извлекаю факты…</div>
                ) : (
                  <>
                    <div className="text-sm font-medium text-ink mb-1">Брось произвольный PDF или кликни</div>
                    <div className="text-xs text-ink-mute">любой документ, включая картиночный/скан — Claude распознает и разложит факты по матрице</div>
                  </>
                )}
              </div>
            )}
            {pdfPreviewMut.isError && (
              <div className="text-sm text-red-600 bg-red-50 rounded p-3">{String(pdfPreviewMut.error)}</div>
            )}

            {pdfCands && (
              <div className="space-y-2">
                <div className="flex items-baseline justify-between">
                  <h3 className="text-sm font-semibold">Извлечено из «{pdfTitle}» <span className="font-normal text-ink-mute">({pdfCands.length})</span></h3>
                  <button onClick={() => { setPdfCands(null); pdfPreviewMut.reset(); }} className="text-[11px] text-ink-mute hover:text-ink">другой файл</button>
                </div>
                {pdfCands.length === 0 ? (
                  <div className="text-sm text-ink-mute italic">Фактов не извлечено (или нет ключа LLM). Попробуй другой PDF.</div>
                ) : (
                  <>
                    <p className="text-[11px] text-ink-mute">Источник — этот файл (archival). Отметь, что внести; проверь ячейку и флаг.</p>
                    <ul className="space-y-1.5 max-h-[55vh] overflow-y-auto">
                      {pdfCands.map((c, i) => (
                        <li key={i} className="flex gap-2 text-sm items-baseline border border-ink-line rounded p-2">
                          <input type="checkbox" checked={pdfAccepted.has(i)} onChange={() => togglePdf(i)} className="mt-1" />
                          <span className="text-[10px] font-mono text-ink-mute border border-ink-line rounded px-1 shrink-0">{c.subsection_id}</span>
                          <FlagDot flag={c.flag as "green" | "red" | "grey"} className="mt-1.5 shrink-0" />
                          <span className="flex-1">{c.text}<span className="text-[11px] text-ink-mute"> · {c.subsection_name}</span></span>
                        </li>
                      ))}
                    </ul>
                    <div className="flex items-center gap-2 pt-1">
                      <button onClick={() => pdfCommitMut.mutate()} disabled={pdfCommitMut.isPending || pdfAccepted.size === 0}
                        className="text-sm px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                        {pdfCommitMut.isPending ? "Вношу…" : `Внести в матрицу (${pdfAccepted.size})`}
                      </button>
                      {pdfCommitMut.isSuccess && <span className="text-xs text-emerald-700">внесено ✓</span>}
                      {pdfCommitMut.isError && <span className="text-xs text-red-600">{String(pdfCommitMut.error)}</span>}
                    </div>
                  </>
                )}
              </div>
            )}
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
          {(r.held_facts ?? 0) > 0 && (
            <div className="text-sm text-amber-700 mt-1">
              {r.held_facts} придержано воротами — см. Health → «Проверка фактов»
            </div>
          )}
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
