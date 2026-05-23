import { useState, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Layer, YouTubeFact, YouTubePreviewResult, YouTubeSkipped } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
  layers?: Layer[];
}

export interface FactEdit {
  text_ru?: string;
  subsection_id?: string;
  flag?: string;
}

function editIsEmpty(e: FactEdit | undefined): boolean {
  return !e || (!e.text_ru && !e.subsection_id && !e.flag);
}

const FLAG_COLORS: Record<string, string> = {
  green: "text-emerald-700 bg-emerald-50 border-emerald-200",
  red: "text-red-700 bg-red-50 border-red-200",
  grey: "text-slate-500 bg-slate-50 border-slate-200",
};

function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function IngestYouTube({ clientId, onJumpToCell, layers }: Props) {
  const lsKey = `yt-ingest-${clientId}`;
  const lsSaved = (() => { try { return JSON.parse(localStorage.getItem(lsKey) || "{}"); } catch { return {}; } })();

  const subsectionOptions = (layers ?? []).flatMap(L =>
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${s.name} (${L.name})` }))
  );

  const [screen, setScreen] = useState<"input" | "history" | "preview" | "done">(lsSaved.screen || "input");
  const [url, setUrl] = useState(lsSaved.url || "");
  const [preview, setPreview] = useState<YouTubePreviewResult | null>(lsSaved.preview || null);
  const [readOnly, setReadOnly] = useState(false);
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [overrides, setOverrides] = useState<Set<number>>(new Set());
  const [factEdits, setFactEdits] = useState<Record<number, FactEdit>>(lsSaved.factEdits || {});
  const [skippedEdits, setSkippedEdits] = useState<Record<number, FactEdit>>(lsSaved.skippedEdits || {});
  const [expertEmail, setExpertEmail] = useState("");
  const [jobId, setJobId] = useState<string | null>(lsSaved.jobId || null);
  const [jobStatus, setJobStatus] = useState<string>(lsSaved.jobStatus || "");
  const [reopenLoading, setReopenLoading] = useState<string | null>(null);
  const [reopenError, setReopenError] = useState<string>("");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Pick up ?url= query param from Research-tab redirect — prefill input
  // and switch back to input screen if currently in preview/history view.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const incoming = searchParams.get("url");
    if (!incoming) return;
    setUrl(incoming);
    setScreen("input");
    setPreview(null);
    setReadOnly(false);
    setJobId(null);
    setJobStatus("");
    setDropped(new Set());
    setOverrides(new Set());
    setSelected(new Set());
    setFactEdits({});
    setSkippedEdits({});
    saveState({
      url: incoming, screen: "input",
      jobId: null, jobStatus: "", preview: null,
      factEdits: {}, skippedEdits: {},
    });
    // strip the param so a refresh doesn't keep re-prefilling
    const next = new URLSearchParams(searchParams);
    next.delete("url");
    setSearchParams(next, { replace: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qc = useQueryClient();

  function saveState(patch: Record<string, unknown>) {
    try {
      const cur = JSON.parse(localStorage.getItem(lsKey) || "{}");
      localStorage.setItem(lsKey, JSON.stringify({ ...cur, ...patch }));
    } catch {}
  }

  function clearState() {
    try { localStorage.removeItem(lsKey); } catch {}
  }

  const history = useQuery({
    queryKey: ["yt-ingest-history", clientId],
    queryFn: () => api.youtubeHistory(clientId),
  });

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  // Resume polling if we have a jobId that was processing when tab was left
  useEffect(() => {
    if (jobId && jobStatus === "processing" && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.youtubePreviewStatus(clientId, jobId);
          setJobStatus(status.status);
          if (status.status === "done" && status.result) {
            stopPolling();
            setPreview(status.result);
            setReadOnly(false);
            setDropped(new Set());
            setOverrides(new Set());
            setSelected(new Set());
            setFactEdits({});
            setSkippedEdits({});
            setScreen("preview");
            saveState({ screen: "preview", preview: status.result, jobStatus: "done",
                       factEdits: {}, skippedEdits: {} });
          } else if (status.status === "error") {
            stopPolling();
            saveState({ jobStatus: "error" });
          }
        } catch { stopPolling(); }
      }, 5000);
    }
    return () => stopPolling();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const previewMut = useMutation({
    mutationFn: () => api.youtubePreviewStart(clientId, url),
    onSuccess: (job) => {
      setJobId(job.job_id);
      setJobStatus("processing");
      saveState({ jobId: job.job_id, jobStatus: "processing", url });
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.youtubePreviewStatus(clientId, job.job_id);
          setJobStatus(status.status);
          if (status.status === "done" && status.result) {
            stopPolling();
            setPreview(status.result);
            setReadOnly(false);
            setDropped(new Set());
            setOverrides(new Set());
            setSelected(new Set());
            setFactEdits({});
            setSkippedEdits({});
            setScreen("preview");
            saveState({ screen: "preview", preview: status.result, jobStatus: "done",
                       factEdits: {}, skippedEdits: {} });
          } else if (status.status === "error") {
            stopPolling();
            saveState({ jobStatus: "error" });
          }
        } catch { stopPolling(); }
      }, 5000);
    },
  });

  const commitMut = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("No preview");
      const accepted = preview.facts
        .map((_, i) => i)
        .filter((i) => !dropped.has(i));

      const ov: any[] = [];
      // Edits for accepted facts
      for (const i of accepted) {
        const e = factEdits[i];
        if (!editIsEmpty(e)) {
          ov.push({ kind: "fact", idx: i, ...e });
        }
      }
      // Skipped overrides (with optional edit)
      for (const i of Array.from(overrides)) {
        const e = skippedEdits[i] || {};
        ov.push({ kind: "skipped", idx: i, force_keep: true, ...e });
      }

      return api.youtubeCommit(
        clientId,
        preview.preview_id,
        accepted,
        ov,
        expertEmail || "anonymous@example.com",
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      qc.invalidateQueries({ queryKey: ["yt-ingest-history", clientId] });
      setScreen("done");
    },
  });

  const keptCount = preview
    ? preview.facts.filter((_, i) => !dropped.has(i)).length
    : 0;

  function updateFactEdit(idx: number, patch: FactEdit) {
    setFactEdits((prev) => {
      const next = { ...prev };
      const merged = { ...next[idx], ...patch };
      // Clean empty values so editIsEmpty returns true again
      Object.keys(merged).forEach((k) => {
        const v = (merged as any)[k];
        if (v === "" || v === undefined || v === null) delete (merged as any)[k];
      });
      if (Object.keys(merged).length === 0) delete next[idx]; else next[idx] = merged;
      saveState({ factEdits: next });
      return next;
    });
  }

  async function reopenPreview(previewId: string) {
    setReopenLoading(previewId);
    setReopenError("");
    try {
      const result = await api.youtubePreviewById(clientId, previewId);
      setPreview(result);
      setReadOnly(true);
      setDropped(new Set());
      setOverrides(new Set());
      setSelected(new Set());
      setFactEdits({});
      setSkippedEdits({});
      setScreen("preview");
    } catch (e) {
      setReopenError(e instanceof Error ? e.message : String(e));
    } finally {
      setReopenLoading(null);
    }
  }

  function updateSkippedEdit(idx: number, patch: FactEdit) {
    setSkippedEdits((prev) => {
      const next = { ...prev };
      const merged = { ...next[idx], ...patch };
      Object.keys(merged).forEach((k) => {
        const v = (merged as any)[k];
        if (v === "" || v === undefined || v === null) delete (merged as any)[k];
      });
      if (Object.keys(merged).length === 0) delete next[idx]; else next[idx] = merged;
      saveState({ skippedEdits: next });
      return next;
    });
  }

  function toggleSelect(idx: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  }

  function bulkDrop() {
    setDropped((prev) => {
      const next = new Set(prev);
      selected.forEach((i) => next.add(i));
      return next;
    });
  }

  function bulkRestore() {
    setDropped((prev) => {
      const next = new Set(prev);
      selected.forEach((i) => next.delete(i));
      return next;
    });
  }

  function bulkSetFlag(flag: "green" | "red" | "grey") {
    if (!preview) return;
    setFactEdits((prev) => {
      const next = { ...prev };
      selected.forEach((idx) => {
        const original = preview.facts[idx];
        if (!original) return;
        const cur = next[idx] || {};
        const newEdit: FactEdit = { ...cur };
        if (flag === original.flag) {
          delete newEdit.flag;
        } else {
          newEdit.flag = flag;
        }
        if (Object.keys(newEdit).length === 0) {
          delete next[idx];
        } else {
          next[idx] = newEdit;
        }
      });
      saveState({ factEdits: next });
      return next;
    });
  }

  function bulkMoveTo(sid: string) {
    if (!preview || !sid) return;
    setFactEdits((prev) => {
      const next = { ...prev };
      selected.forEach((idx) => {
        const original = preview.facts[idx];
        if (!original) return;
        const cur = next[idx] || {};
        const newEdit: FactEdit = { ...cur };
        if (sid === original.subsection_id) {
          delete newEdit.subsection_id;
        } else {
          newEdit.subsection_id = sid;
        }
        if (Object.keys(newEdit).length === 0) {
          delete next[idx];
        } else {
          next[idx] = newEdit;
        }
      });
      saveState({ factEdits: next });
      return next;
    });
  }

  // ── Input screen ─────────────────────────────────────────────────────────

  if (screen === "input") {
    return (
      <div className="p-5 max-w-2xl space-y-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Ingest YouTube Interview</h2>
          {history.data && history.data.length > 0 && (
            <button
              onClick={() => setScreen("history")}
              className="text-xs text-ink-mute hover:text-ink underline-offset-2 hover:underline"
            >
              History ({history.data.length}) →
            </button>
          )}
        </div>

        <div className="space-y-2">
          <label className="block text-xs font-medium text-ink-mute">YouTube URL</label>
          <div className="flex gap-2">
            <input
              type="url"
              placeholder="https://youtube.com/watch?v=..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && url.trim()) previewMut.mutate();
              }}
              className="flex-1 text-sm border border-ink-line rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-ink"
            />
            <button
              onClick={() => previewMut.mutate()}
              disabled={!url.trim() || previewMut.isPending}
              className={`px-4 py-2 text-sm rounded font-medium transition ${
                !url.trim() || previewMut.isPending
                  ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                  : "bg-ink text-white hover:bg-ink/90"
              }`}
            >
              {previewMut.isPending ? "Processing…" : "Preview"}
            </button>
          </div>
          {(previewMut.isPending || jobStatus === "processing") && (
            <div className="text-xs text-ink-mute space-y-1">
              <div>Запущено в фоне — обрабатываем…</div>
              <div className="text-[10px] text-slate-400">
                Скачиваем аудио → транскрибируем → извлекаем факты.
                Для часового видео ~5–15 мин. Можно закрыть этот таб и вернуться.
              </div>
            </div>
          )}
          {jobStatus === "error" && (
            <div className="text-sm text-red-600 bg-red-50 rounded p-3">
              Ошибка: {previewMut.error ? String(previewMut.error) : "что-то пошло не так"}
            </div>
          )}
        </div>


        {/* History teaser: last 5, full list lives on History screen */}
        {history.data && history.data.length > 0 && (
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <div className="text-xs font-medium text-ink-mute uppercase tracking-wide">
                Recent ingests
              </div>
              {history.data.length > 5 && (
                <button
                  onClick={() => setScreen("history")}
                  className="text-[10px] text-ink-mute hover:text-ink"
                >
                  View all {history.data.length} →
                </button>
              )}
            </div>
            <table className="w-full text-xs">
              <thead className="text-[10px] text-ink-mute uppercase">
                <tr>
                  <th className="text-left py-1 pr-3">Date</th>
                  <th className="text-left py-1 pr-3">Video</th>
                  <th className="text-right py-1 pr-3">Emitted</th>
                  <th className="text-right py-1 pr-3">Committed</th>
                  <th className="text-right py-1"></th>
                </tr>
              </thead>
              <tbody>
                {history.data.slice(0, 5).map((row) => (
                  <tr key={row.id} className="border-t border-ink-line">
                    <td className="py-1.5 pr-3 font-mono">
                      {new Date(row.parsed_at).toLocaleDateString()}
                    </td>
                    <td className="py-1.5 pr-3 truncate max-w-[140px]">
                      {row.video_id ?? "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{row.facts_emitted}</td>
                    <td className="py-1.5 pr-3 text-right">
                      {row.confirmed_at ? row.facts_committed : <span className="text-amber-600">pending</span>}
                    </td>
                    <td className="py-1.5 text-right">
                      <button
                        onClick={() => reopenPreview(row.id)}
                        disabled={reopenLoading === row.id}
                        className="text-[10px] text-blue-600 hover:underline disabled:text-slate-400"
                      >
                        {reopenLoading === row.id ? "loading…" : "reopen"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {reopenError && <div className="text-xs text-red-600 mt-2">{reopenError}</div>}
          </div>
        )}
      </div>
    );
  }

  // ── History screen ─────────────────────────────────────────────────────────

  if (screen === "history") {
    const rows = history.data ?? [];
    return (
      <div className="p-5 max-w-5xl space-y-4">
        <div className="flex items-baseline justify-between">
          <div>
            <h2 className="text-lg font-semibold">YouTube Ingest History</h2>
            <div className="text-xs text-ink-mute mt-0.5">
              {rows.length} past ingest{rows.length !== 1 ? "s" : ""} for this client
            </div>
          </div>
          <button
            onClick={() => { setScreen("input"); setReopenError(""); }}
            className="text-xs text-ink-mute hover:text-ink"
          >
            ← Back to input
          </button>
        </div>
        {history.isLoading && <div className="text-sm text-ink-mute">Loading…</div>}
        {rows.length === 0 && !history.isLoading && (
          <div className="text-sm text-ink-mute">No ingests yet.</div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-[10px] text-ink-mute uppercase">
              <tr className="border-b border-ink-line">
                <th className="text-left py-2 pr-3">Date</th>
                <th className="text-left py-2 pr-3">Video</th>
                <th className="text-left py-2 pr-3">Transcriber</th>
                <th className="text-right py-2 pr-3">Cost</th>
                <th className="text-right py-2 pr-3">Emitted</th>
                <th className="text-right py-2 pr-3">Committed</th>
                <th className="text-right py-2 pr-3">Warnings</th>
                <th className="text-left py-2 pr-3">Expert</th>
                <th className="text-right py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-ink-line hover:bg-slate-50">
                  <td className="py-2 pr-3 font-mono whitespace-nowrap">
                    {new Date(row.parsed_at).toLocaleString()}
                  </td>
                  <td className="py-2 pr-3 truncate max-w-[160px]">
                    {row.video_id ?? "—"}
                  </td>
                  <td className="py-2 pr-3 text-ink-mute">{row.transcriber ?? "—"}</td>
                  <td className="py-2 pr-3 text-right text-ink-mute">
                    {row.transcribe_cost_usd != null ? `$${row.transcribe_cost_usd.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">{row.facts_emitted}</td>
                  <td className="py-2 pr-3 text-right">
                    {row.confirmed_at ? (
                      <span className="text-emerald-700">{row.facts_committed}</span>
                    ) : (
                      <span className="text-amber-600">pending</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right">{row.channel_warnings}</td>
                  <td className="py-2 pr-3 text-ink-mute truncate max-w-[160px]">
                    {row.expert_email || "—"}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => reopenPreview(row.id)}
                      disabled={reopenLoading === row.id}
                      className="text-[11px] text-blue-600 hover:underline disabled:text-slate-400"
                    >
                      {reopenLoading === row.id ? "loading…" : "reopen"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {reopenError && (
          <div className="text-xs text-red-600 bg-red-50 rounded p-2">{reopenError}</div>
        )}
      </div>
    );
  }

  // ── Done screen ────────────────────────────────────────────────────────────

  if (screen === "done" && commitMut.data) {
    const r = commitMut.data;
    return (
      <div className="p-5 max-w-2xl space-y-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="font-semibold text-emerald-800 mb-1">Saved to matrix</div>
          <div className="text-sm text-emerald-700">
            {r.committed} fact{r.committed !== 1 ? "s" : ""} committed ·{" "}
            {r.skipped} skipped (duplicates or dropped)
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => onJumpToCell(preview?.facts[0]?.subsection_id ?? "2.1")}
            className="px-4 py-2 text-sm bg-ink text-white rounded hover:bg-ink/90"
          >
            View in Matrix
          </button>
          <button
            onClick={() => {
              clearState();
              setScreen("input");
              setPreview(null);
              setReadOnly(false);
              setUrl("");
              setJobId(null);
              setJobStatus("");
              stopPolling();
              previewMut.reset();
              commitMut.reset();
            }}
            className="px-4 py-2 text-sm border border-ink-line rounded hover:bg-slate-50"
          >
            Ingest another
          </button>
        </div>
      </div>
    );
  }

  // ── Preview screen ─────────────────────────────────────────────────────────

  if (!preview) return null;

  return (
    <div className="p-5 max-w-4xl space-y-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {readOnly ? "Past Preview (review-only)" : "Preview"}
          </h2>
          <div className="text-xs text-ink-mute mt-0.5">
            {preview.facts.length} facts · {preview.skipped.length} skipped by LayerGuard
          </div>
        </div>
        <button
          onClick={() => {
            if (readOnly) {
              setReadOnly(false);
              setPreview(null);
              setScreen("history");
            } else {
              setScreen("input");
              previewMut.reset();
            }
          }}
          className="text-xs text-ink-mute hover:text-ink"
        >
          ← Back
        </button>
      </div>

      {readOnly && (
        <div className="bg-slate-100 border border-slate-300 rounded-lg p-3 text-sm text-slate-700">
          {preview.confirmed_at ? (
            <>
              <span className="font-medium">Committed</span> on{" "}
              {new Date(preview.confirmed_at).toLocaleString()} —
              read-only review. Edits and re-commit disabled.
            </>
          ) : (
            <>
              <span className="font-medium">Uncommitted preview</span> from history — read-only review.
              To re-ingest this video, return to input and paste the URL again.
            </>
          )}
        </div>
      )}

      {/* Video meta */}
      <div className="bg-slate-50 border border-ink-line rounded-lg p-4 space-y-1 text-sm">
        <div className="font-medium">{preview.meta.title}</div>
        <div className="text-xs text-ink-mute">
          {preview.meta.channel_name} · {fmtDuration(preview.meta.duration_sec)}
          {preview.meta.view_count != null &&
            ` · ${preview.meta.view_count.toLocaleString()} views`}
          {preview.meta.like_count != null &&
            ` · ${preview.meta.like_count.toLocaleString()} likes`}
          {preview.meta.upload_date && ` · ${preview.meta.upload_date}`}
          {preview.from_cache && " · transcript from cache"}
          {preview.transcribe_cost_usd != null &&
            ` · ~$${preview.transcribe_cost_usd.toFixed(2)} (OpenAI Whisper)`}
        </div>
        <a
          href={preview.meta.canonical_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:underline"
        >
          {preview.meta.canonical_url}
        </a>
      </div>

      {/* Orientation brief — paragraph + per-cell coverage */}
      {(preview.video_brief || (preview.cell_briefs && Object.keys(preview.cell_briefs).length > 0)) && (
        <div className="border border-ink-line rounded-lg p-4 space-y-3 bg-white">
          {preview.video_brief && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1">
                Brief
              </div>
              <div className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
                {preview.video_brief}
              </div>
            </div>
          )}
          {preview.cell_briefs && Object.keys(preview.cell_briefs).length > 0 && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1">
                Coverage ({Object.keys(preview.cell_briefs).length} cells)
              </div>
              <ul className="space-y-1">
                {Object.entries(preview.cell_briefs)
                  .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
                  .map(([sid, brief]) => (
                    <li key={sid} className="text-sm flex gap-2">
                      <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600 shrink-0 mt-0.5">
                        {sid}
                      </span>
                      <span className="text-slate-700">{brief}</span>
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Original video description (collapsed) */}
      {preview.meta.description && preview.meta.description.trim() && (
        <details className="text-xs text-ink-mute">
          <summary className="cursor-pointer hover:text-ink">
            Original video description ({preview.meta.description.length} chars)
          </summary>
          <div className="mt-2 text-slate-600 whitespace-pre-wrap border-l-2 border-slate-200 pl-3">
            {preview.meta.description}
          </div>
        </details>
      )}

      {/* Chunk-failure warning: facts may be missing from those time windows */}
      {(preview.stats.chunks_failed ?? 0) > 0 && (
        <div className="bg-amber-50 border border-amber-300 rounded-lg p-3 text-sm text-amber-900">
          <div className="font-medium">
            ⚠ {preview.stats.chunks_failed} of {preview.stats.chunks_total ?? "?"} chunks failed
          </div>
          <div className="text-xs mt-1">
            Some 15-min windows produced no facts because the LLM returned an empty
            or unparseable response (likely rate-limit / overload). Re-run preview to retry — transcript is cached, retry is free.
          </div>
        </div>
      )}

      {/* Parser notes */}
      {preview.notes.length > 0 && (
        <details className="text-xs text-ink-mute">
          <summary className="cursor-pointer hover:text-ink">
            {preview.notes.length} note{preview.notes.length !== 1 ? "s" : ""}
          </summary>
          <ul className="mt-1 space-y-0.5 pl-3">
            {preview.notes.map((n, i) => <li key={i}>— {n}</li>)}
          </ul>
        </details>
      )}

      {/* Facts */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-xs font-medium uppercase text-ink-mute tracking-wide">
            Facts ({preview.facts.length})
          </div>
          {!readOnly && (
            <div className="flex items-center gap-2 text-[10px]">
              <button
                onClick={() => setSelected(new Set(preview.facts.map((_, i) => i)))}
                className="text-ink-mute hover:text-ink"
              >
                select all
              </button>
              <span className="text-slate-300">·</span>
              <button
                onClick={() => setSelected(new Set())}
                className="text-ink-mute hover:text-ink"
                disabled={selected.size === 0}
              >
                clear
              </button>
            </div>
          )}
        </div>

        {/* Bulk-actions toolbar */}
        {!readOnly && selected.size > 0 && (
          <div className="sticky top-0 z-10 mb-3 bg-amber-50 border border-amber-300 rounded-lg p-3 flex flex-wrap items-center gap-2 text-xs shadow-sm">
            <span className="font-medium text-amber-900">
              {selected.size} selected
            </span>
            <div className="h-4 w-px bg-amber-300" />
            <button
              onClick={bulkDrop}
              className="px-2 py-1 border border-red-300 text-red-700 rounded hover:bg-red-50"
            >
              drop
            </button>
            <button
              onClick={bulkRestore}
              className="px-2 py-1 border border-emerald-300 text-emerald-700 rounded hover:bg-emerald-50"
            >
              restore
            </button>
            <div className="h-4 w-px bg-amber-300" />
            <span className="text-amber-900">flag →</span>
            {(["green", "red", "grey"] as const).map((f) => (
              <button
                key={f}
                onClick={() => bulkSetFlag(f)}
                className={`px-2 py-1 border rounded ${FLAG_COLORS[f]}`}
              >
                {f}
              </button>
            ))}
            <div className="h-4 w-px bg-amber-300" />
            <span className="text-amber-900">move →</span>
            <select
              onChange={(e) => {
                if (e.target.value) {
                  bulkMoveTo(e.target.value);
                  e.target.value = "";
                }
              }}
              defaultValue=""
              className="text-xs border border-amber-300 rounded px-2 py-1 bg-white"
            >
              <option value="" disabled>subsection…</option>
              {subsectionOptions.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => setSelected(new Set())}
              className="ml-auto text-[10px] text-amber-900 hover:text-amber-700"
            >
              ✕ clear
            </button>
          </div>
        )}

        <div className="space-y-2">
          {preview.facts.map((fact, idx) => (
            <FactCard
              key={idx}
              fact={fact}
              edit={factEdits[idx]}
              dropped={dropped.has(idx)}
              readOnly={readOnly}
              selected={selected.has(idx)}
              onToggleSelect={() => toggleSelect(idx)}
              subsectionOptions={subsectionOptions}
              onToggleDrop={() => setDropped((prev) => {
                const next = new Set(prev);
                next.has(idx) ? next.delete(idx) : next.add(idx);
                return next;
              })}
              onEdit={(patch) => updateFactEdit(idx, patch)}
            />
          ))}
        </div>
      </div>

      {/* Skipped facts (LayerGuard) */}
      {preview.skipped.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
            Skipped by LayerGuard ({preview.skipped.length})
          </div>
          <div className="space-y-2">
            {preview.skipped.map((s, idx) => (
              <SkippedCard
                key={idx}
                skipped={s}
                edit={skippedEdits[idx]}
                overridden={overrides.has(idx)}
                readOnly={readOnly}
                subsectionOptions={subsectionOptions}
                onToggleOverride={() => setOverrides((prev) => {
                  const next = new Set(prev);
                  next.has(idx) ? next.delete(idx) : next.add(idx);
                  return next;
                })}
                onEdit={(patch) => updateSkippedEdit(idx, patch)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Commit bar — hidden in read-only review mode */}
      {!readOnly && (
      <div className="sticky bottom-0 bg-white border-t border-ink-line pt-4 pb-2 space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="email"
            placeholder="your@email.com"
            value={expertEmail}
            onChange={(e) => setExpertEmail(e.target.value)}
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
      )}
    </div>
  );
}

// ── FactCard ──────────────────────────────────────────────────────────────────

interface FactCardProps {
  fact: YouTubeFact;
  edit?: FactEdit;
  dropped: boolean;
  readOnly?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
  subsectionOptions: { id: string; label: string }[];
  onToggleDrop: () => void;
  onEdit: (patch: FactEdit) => void;
}

function FactCard({ fact, edit, dropped, readOnly, selected, onToggleSelect, subsectionOptions, onToggleDrop, onEdit }: FactCardProps) {
  const [editing, setEditing] = useState(false);
  const effectiveTextRu = edit?.text_ru ?? (fact.text_ru || fact.text);
  const effectiveSid = edit?.subsection_id ?? fact.subsection_id;
  const effectiveFlag = (edit?.flag ?? fact.flag) as string;
  const flagStyle = FLAG_COLORS[effectiveFlag] ?? FLAG_COLORS.grey;
  const tSec = Math.floor(fact.snippet_start_sec);
  const timeStr = `${Math.floor(tSec / 60)}:${String(tSec % 60).padStart(2, "0")}`;
  const displayRu = effectiveTextRu;
  const displayEn = fact.text_en || "";
  const displayQuote = fact.quote || fact.evidence_snippet || "";
  const isEdited = !editIsEmpty(edit);

  return (
    <div className={`border rounded-lg p-3 text-sm transition ${
      dropped ? "opacity-40 bg-slate-50" : "bg-white"
    } border-l-4 ${
      effectiveFlag === "green" ? "border-l-emerald-400" :
      effectiveFlag === "red" ? "border-l-red-400" : "border-l-slate-300"
    } ${isEdited ? "ring-1 ring-amber-300" : ""} ${selected ? "ring-2 ring-amber-400" : ""}`}>
      <div className="flex items-start gap-2">
        {/* Selection checkbox (hidden in readonly) */}
        {!readOnly && onToggleSelect && (
          <input
            type="checkbox"
            checked={!!selected}
            onChange={onToggleSelect}
            className="mt-1 shrink-0 cursor-pointer"
            aria-label="Select fact for bulk action"
          />
        )}
        {/* Left: badges */}
        <div className="flex flex-col gap-1 shrink-0 mt-0.5">
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border text-center ${
            edit?.subsection_id
              ? "bg-amber-50 border-amber-200 text-amber-700"
              : "bg-slate-100 border-slate-200 text-slate-600"
          }`}>
            {effectiveSid}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border text-center ${flagStyle}`}>
            {effectiveFlag}
          </span>
        </div>

        {/* Center: content */}
        <div className="flex-1 min-w-0 space-y-1.5">
          {!editing ? (
            <>
              <div className={`font-medium text-slate-800 ${dropped ? "line-through" : ""}`}>
                {displayRu}
                {isEdited && <span className="ml-1 text-[10px] text-amber-600">(edited)</span>}
              </div>
              {displayEn && displayEn !== displayRu && (
                <div className="text-xs text-slate-500 italic">{displayEn}</div>
              )}
              {displayQuote && (
                <div className="text-xs text-slate-400 border-l-2 border-slate-200 pl-2 line-clamp-3">
                  "{displayQuote}"
                </div>
              )}
              <div className="flex items-center gap-3">
                <a
                  href={fact.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[10px] text-blue-500 hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  ▶ {timeStr}
                </a>
                {isEdited && (
                  <button
                    onClick={() => onEdit({ text_ru: undefined, subsection_id: undefined, flag: undefined })}
                    className="text-[10px] text-amber-600 hover:underline"
                  >
                    revert edits
                  </button>
                )}
              </div>
            </>
          ) : (
            <FactEditForm
              defaultTextRu={effectiveTextRu}
              defaultSid={effectiveSid}
              defaultFlag={effectiveFlag}
              originalTextRu={fact.text_ru || fact.text}
              originalSid={fact.subsection_id}
              originalFlag={fact.flag}
              subsectionOptions={subsectionOptions}
              onSave={(patch) => { onEdit(patch); setEditing(false); }}
              onCancel={() => setEditing(false)}
              quote={displayQuote}
              textEn={displayEn}
            />
          )}
        </div>

        {/* Right: actions (hidden in read-only review) */}
        {!readOnly && (
          <div className="flex flex-col gap-1 shrink-0">
            <button
              onClick={() => setEditing((e) => !e)}
              className="text-[10px] px-2 py-0.5 border border-slate-300 text-slate-600 rounded hover:bg-slate-100"
            >
              {editing ? "close" : "edit"}
            </button>
            <button
              onClick={onToggleDrop}
              className={`text-[10px] px-2 py-0.5 border rounded ${
                dropped
                  ? "border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                  : "border-red-200 text-red-600 hover:bg-red-50"
              }`}
            >
              {dropped ? "restore" : "drop"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── FactEditForm (shared by FactCard and SkippedCard) ─────────────────────────

interface FactEditFormProps {
  defaultTextRu: string;
  defaultSid: string;
  defaultFlag: string;
  originalTextRu: string;
  originalSid: string;
  originalFlag: string;
  subsectionOptions: { id: string; label: string }[];
  quote: string;
  textEn: string;
  onSave: (patch: FactEdit) => void;
  onCancel: () => void;
}

function FactEditForm({
  defaultTextRu, defaultSid, defaultFlag,
  originalTextRu, originalSid, originalFlag,
  subsectionOptions, quote, textEn, onSave, onCancel,
}: FactEditFormProps) {
  const [textRu, setTextRu] = useState(defaultTextRu);
  const [sid, setSid] = useState(defaultSid);
  const [flag, setFlag] = useState(defaultFlag);

  function handleSave() {
    onSave({
      text_ru: textRu.trim() === originalTextRu ? undefined : textRu.trim(),
      subsection_id: sid === originalSid ? undefined : sid,
      flag: flag === originalFlag ? undefined : flag,
    });
  }

  return (
    <div className="space-y-2">
      <textarea
        value={textRu}
        onChange={(e) => setTextRu(e.target.value)}
        rows={3}
        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ink"
      />
      {textEn && (
        <div className="text-xs text-slate-400 italic">EN (read-only): {textEn}</div>
      )}
      {quote && (
        <div className="text-xs text-slate-400 border-l-2 border-slate-200 pl-2 line-clamp-2 italic">
          "{quote}"
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={sid}
          onChange={(e) => setSid(e.target.value)}
          className="text-xs border border-slate-300 rounded px-2 py-1"
        >
          {subsectionOptions.length === 0 && <option value={sid}>{sid}</option>}
          {subsectionOptions.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {(["green", "red", "grey"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFlag(f)}
              className={`text-[10px] px-2 py-0.5 border rounded ${
                flag === f ? FLAG_COLORS[f] + " font-medium" : "border-slate-200 text-slate-400"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={onCancel}
            className="text-[10px] px-2 py-0.5 border border-slate-300 text-slate-600 rounded hover:bg-slate-100"
          >
            cancel
          </button>
          <button
            onClick={handleSave}
            className="text-[10px] px-3 py-0.5 bg-ink text-white rounded hover:bg-ink/90"
          >
            save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── SkippedCard ───────────────────────────────────────────────────────────────

interface SkippedCardProps {
  skipped: YouTubeSkipped;
  edit?: FactEdit;
  overridden: boolean;
  readOnly?: boolean;
  subsectionOptions: { id: string; label: string }[];
  onToggleOverride: () => void;
  onEdit: (patch: FactEdit) => void;
}

function SkippedCard({ skipped, edit, overridden, readOnly, subsectionOptions, onToggleOverride, onEdit }: SkippedCardProps) {
  const [editing, setEditing] = useState(false);
  const effectiveTextRu = edit?.text_ru ?? (skipped.text_ru || skipped.text);
  const effectiveSid = edit?.subsection_id ?? skipped.subsection_id;
  const effectiveFlag = (edit?.flag ?? skipped.flag ?? "green") as string;
  const tSec = Math.floor(skipped.snippet_start_sec ?? 0);
  const timeStr = `${Math.floor(tSec / 60)}:${String(tSec % 60).padStart(2, "0")}`;
  const displayRu = effectiveTextRu;
  const displayEn = skipped.text_en || "";
  const displayQuote = skipped.quote || skipped.evidence_snippet || "";
  const isEdited = !editIsEmpty(edit);

  return (
    <div className={`border rounded-lg p-3 text-sm ${
      overridden ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50 opacity-80"
    } ${isEdited ? "ring-1 ring-amber-300" : ""}`}>
      <div className="flex items-start gap-2">
        <div className="flex flex-col gap-1 shrink-0 mt-0.5">
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border text-center ${
            edit?.subsection_id
              ? "bg-amber-50 border-amber-200 text-amber-700"
              : "bg-white/60 border-slate-200 text-slate-500"
          }`}>
            {effectiveSid}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-200 text-slate-500 text-center">
            ⚠ skipped
          </span>
        </div>

        <div className="flex-1 min-w-0 space-y-1.5">
          {!editing ? (
            <>
              <div className="font-medium text-slate-700">
                {displayRu}
                {isEdited && <span className="ml-1 text-[10px] text-amber-600">(edited)</span>}
              </div>
              {displayEn && displayEn !== displayRu && (
                <div className="text-xs text-slate-500 italic">{displayEn}</div>
              )}
              <div className="text-[10px] text-slate-400">{skipped.reason}</div>
              {displayQuote && (
                <div className="text-xs text-slate-400 border-l-2 border-slate-200 pl-2 line-clamp-3 italic">
                  "{displayQuote}"
                </div>
              )}
              <div className="flex items-center gap-3">
                {skipped.source_url && (
                  <a
                    href={skipped.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[10px] text-blue-500 hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    ▶ {timeStr}
                  </a>
                )}
                {isEdited && (
                  <button
                    onClick={() => onEdit({ text_ru: undefined, subsection_id: undefined, flag: undefined })}
                    className="text-[10px] text-amber-600 hover:underline"
                  >
                    revert edits
                  </button>
                )}
              </div>
            </>
          ) : (
            <FactEditForm
              defaultTextRu={effectiveTextRu}
              defaultSid={effectiveSid}
              defaultFlag={effectiveFlag}
              originalTextRu={skipped.text_ru || skipped.text}
              originalSid={skipped.subsection_id}
              originalFlag={skipped.flag || "green"}
              subsectionOptions={subsectionOptions}
              onSave={(patch) => { onEdit(patch); setEditing(false); }}
              onCancel={() => setEditing(false)}
              quote={displayQuote}
              textEn={displayEn}
            />
          )}
        </div>

        {!readOnly && (
          <div className="flex flex-col gap-1 shrink-0">
            <button
              onClick={() => setEditing((e) => !e)}
              className="text-[10px] px-2 py-0.5 border border-slate-300 text-slate-600 rounded hover:bg-slate-100"
            >
              {editing ? "close" : "edit"}
            </button>
            {skipped.override_allowed && (
              <button
                onClick={onToggleOverride}
                className={`text-[10px] px-2 py-0.5 border rounded ${
                  overridden
                    ? "border-amber-400 text-amber-700 bg-amber-100"
                    : "border-slate-300 text-slate-500 hover:border-amber-300 hover:text-amber-600"
                }`}
              >
                {overridden ? "undo" : "keep"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
