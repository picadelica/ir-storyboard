import { useState, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type { DuplicateHint, Entity, Layer, YouTubeFact, YouTubePreviewResult, YouTubeSkipped } from "../types";
import SourceLine from "./SourceLine";
import FlagDot from "./FlagDot";
import EpisodeOverview from "./EpisodeOverview";

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

export function editIsEmpty(e: FactEdit | undefined): boolean {
  return !e || (!e.text_ru && !e.subsection_id && !e.flag);
}

const FLAG_COLORS: Record<string, string> = {
  green: "text-emerald-700 bg-emerald-50 border-emerald-200",
  red: "text-red-700 bg-red-50 border-red-200",
  grey: "text-slate-500 bg-slate-50 border-slate-200",
};

export function fmtDuration(sec: number): string {
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
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${subsectionNameRu(s.id, s.name)} (${layerNameRu(L.id, L.name)})` }))
  );

  // Restore only lightweight fields — preview JSON can be 200-500 KB and is
  // already stored server-side (reopen via History).
  const restoredScreen = lsSaved.screen === "preview" ? "input" : (lsSaved.screen || "input");
  const [screen, setScreen] = useState<"input" | "history" | "preview" | "done">(restoredScreen);
  const [url, setUrl] = useState(lsSaved.url || "");
  const [preview, setPreview] = useState<YouTubePreviewResult | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [overrides, setOverrides] = useState<Set<number>>(new Set());
  const [factEdits, setFactEdits] = useState<Record<number, FactEdit>>({});
  const [skippedEdits, setSkippedEdits] = useState<Record<number, FactEdit>>({});
  const [expertEmail, setExpertEmail] = useState("");
  const [speakerId, setSpeakerId] = useState<number | null>(null);   // interviewee founder
  const [jobId, setJobId] = useState<string | null>(lsSaved.jobId || null);
  const [jobStatus, setJobStatus] = useState<string>(lsSaved.jobStatus || "");
  const [jobStage, setJobStage] = useState<string>("");
  const [elapsedSec, setElapsedSec] = useState<number>(0);
  const [reopened, setReopened] = useState(false);   // preview came from history reopen
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
  const entities = useQuery<Entity[]>({
    queryKey: ["entities", clientId],
    queryFn: () => api.entities(clientId),
  });
  const founders = (entities.data ?? []).filter(e => e.kind === "founder");
  // 1 founder → auto-attribute; >1 → analyst must pick who the interview is with.
  const effectiveSpeaker = speakerId ?? (founders.length === 1 ? founders[0].id : null);

  // Подсказка «возможный дубль»: похожие активные факты той же ячейки. Ничего не
  // блокирует — аналитик решает сам, игнорирование чипа коммит не меняет.
  const dupHints = useQuery<DuplicateHint[]>({
    queryKey: ["dup-hints", clientId, preview?.preview_id],
    queryFn: () => api.duplicateHints(
      clientId,
      (preview?.facts ?? []).map(f => ({ subsection_id: f.subsection_id, text: f.text_ru || f.text })),
    ),
    enabled: Boolean(preview?.preview_id && (preview?.facts ?? []).length > 0),
  });
  const hintByIdx = new Map((dupHints.data ?? []).map(h => [h.idx, h]));

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  // Elapsed-seconds ticker while a job is processing (drives the status bar timer).
  useEffect(() => {
    if (jobStatus !== "processing") return;
    const t = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [jobStatus]);

  // Resume polling if we have a jobId that was processing when tab was left
  useEffect(() => {
    if (jobId && jobStatus === "processing" && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.youtubePreviewStatus(clientId, jobId);
          setJobStatus(status.status);
          if (status.stage) setJobStage(status.stage);
          if (status.status === "done" && status.result) {
            stopPolling();
            setPreview(status.result);
            setReadOnly(false);
            setReopened(false);
            setDropped(new Set());
            setOverrides(new Set());
            setSelected(new Set());
            setFactEdits({});
            setSkippedEdits({});
            setScreen("preview");
            saveState({ screen: "preview", jobStatus: "done" });
          } else if (status.status === "error") {
            stopPolling();
            saveState({ jobStatus: "error" });
          }
        } catch { stopPolling(); }
      }, 2500);
    }
    return () => stopPolling();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const previewMut = useMutation({
    mutationFn: () => api.youtubePreviewStart(clientId, url),
    onSuccess: (job) => {
      setJobId(job.job_id);
      setJobStatus("processing");
      setJobStage("");
      setElapsedSec(0);
      saveState({ jobId: job.job_id, jobStatus: "processing", url });
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.youtubePreviewStatus(clientId, job.job_id);
          setJobStatus(status.status);
          if (status.stage) setJobStage(status.stage);
          if (status.status === "done" && status.result) {
            stopPolling();
            setPreview(status.result);
            setReadOnly(false);
            setReopened(false);
            setDropped(new Set());
            setOverrides(new Set());
            setSelected(new Set());
            setFactEdits({});
            setSkippedEdits({});
            setScreen("preview");
            saveState({ screen: "preview", jobStatus: "done" });
          } else if (status.status === "error") {
            stopPolling();
            saveState({ jobStatus: "error" });
          }
        } catch { stopPolling(); }
      }, 2500);
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
        effectiveSpeaker,
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
      return next;
    });
  }

  async function reopenPreview(previewId: string) {
    setReopenLoading(previewId);
    setReopenError("");
    try {
      const result = await api.youtubePreviewById(clientId, previewId);
      setPreview(result);
      setReopened(true);
      // Already-committed previews are read-only history; an UNCOMMITTED preview
      // reopened from history is fully editable + committable — this is the path
      // for an analyst who ran several ingests without reviewing and comes back.
      setReadOnly(!!result.confirmed_at);
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
      return next;
    });
  }

  // ── Input screen ─────────────────────────────────────────────────────────

  if (screen === "input") {
    return (
      <div className="p-5 max-w-[820px] mx-auto space-y-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Загрузка YouTube-интервью</h2>
          {history.data && history.data.length > 0 && (
            <button
              onClick={() => setScreen("history")}
              className="text-xs text-ink-mute hover:text-ink underline-offset-2 hover:underline"
            >
              История ({history.data.length}) →
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
              {previewMut.isPending ? "Обрабатываю…" : "Предпросмотр"}
            </button>
          </div>
          {(previewMut.isPending || jobStatus === "processing") && (
            <div className="bg-white rounded-lg border border-ink-line p-5 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 font-medium text-ink">
                  <span className="inline-block w-3 h-3 rounded-full border-2 border-ink/30 border-t-ink animate-spin" />
                  {jobStage || "Запущено в фоне — обрабатываем…"}
                </span>
                <span className="font-mono text-ink-mute tabular-nums">{fmtDuration(elapsedSec)}</span>
              </div>
              {/* Indeterminate progress bar — durations vary, so we show motion, not a %. */}
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <div className="h-full w-1/3 rounded-full bg-ink animate-[ytslide_1.4s_ease-in-out_infinite]" />
              </div>
              <div className="text-[10px] text-slate-400">
                Метаданные → скачиваем аудио → транскрибируем по чанкам → извлекаем факты.
                Для часового видео ~5–15 мин. Можно закрыть таб и вернуться — прогон идёт на сервере.
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
                Последние загрузки
              </div>
              {history.data.length > 5 && (
                <button
                  onClick={() => setScreen("history")}
                  className="text-[10px] text-ink-mute hover:text-ink"
                >
                  Показать все {history.data.length} →
                </button>
              )}
            </div>
            <table className="w-full text-xs">
              <thead className="text-[10px] text-ink-mute uppercase">
                <tr>
                  <th className="text-left py-1 pr-3">Дата</th>
                  <th className="text-left py-1 pr-3">Видео</th>
                  <th className="text-right py-1 pr-3">Извлечено</th>
                  <th className="text-right py-1 pr-3">Внесено</th>
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
                      {row.confirmed_at ? row.facts_committed : <span className="text-amber-600">ожидает</span>}
                    </td>
                    <td className="py-1.5 text-right">
                      <button
                        onClick={() => reopenPreview(row.id)}
                        disabled={reopenLoading === row.id}
                        className="text-[10px] text-blue-600 hover:underline disabled:text-slate-400"
                      >
                        {reopenLoading === row.id ? "загрузка…" : "открыть"}
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
      <div className="p-5 max-w-[820px] mx-auto space-y-4">
        <div className="flex items-baseline justify-between">
          <div>
            <h2 className="text-lg font-semibold">История загрузок YouTube</h2>
            <div className="text-xs text-ink-mute mt-0.5">
              Загрузок для этого клиента: {rows.length}
            </div>
          </div>
          <button
            onClick={() => { setScreen("input"); setReopenError(""); }}
            className="text-xs text-ink-mute hover:text-ink"
          >
            ← Назад к вводу
          </button>
        </div>
        {history.isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
        {rows.length === 0 && !history.isLoading && (
          <div className="text-sm text-ink-mute">Загрузок пока нет.</div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-[10px] text-ink-mute uppercase">
              <tr className="border-b border-ink-line">
                <th className="text-left py-2 pr-3">Дата</th>
                <th className="text-left py-2 pr-3">Видео</th>
                <th className="text-left py-2 pr-3">Транскрибация</th>
                <th className="text-right py-2 pr-3">Стоимость</th>
                <th className="text-right py-2 pr-3">Извлечено</th>
                <th className="text-right py-2 pr-3">Внесено</th>
                <th className="text-right py-2 pr-3">Предупреждения</th>
                <th className="text-left py-2 pr-3">Эксперт</th>
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
                      <span className="text-amber-600">ожидает</span>
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
                      {reopenLoading === row.id ? "загрузка…" : "открыть"}
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
      <div className="p-5 max-w-[820px] mx-auto space-y-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="font-semibold text-emerald-800 mb-1">Сохранено в матрицу</div>
          <div className="text-sm text-emerald-700">
            Внесено фактов: {r.committed} · пропущено: {r.skipped} (дубли или снятые карточки)
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => onJumpToCell(preview?.facts[0]?.subsection_id ?? "2.1")}
            className="px-4 py-2 text-sm bg-ink text-white rounded hover:bg-ink/90"
          >
            Открыть в матрице
          </button>
          <button
            onClick={() => {
              clearState();
              setScreen("input");
              setPreview(null);
              setReadOnly(false);
              setReopened(false);
              setUrl("");
              setJobId(null);
              setJobStatus("");
              stopPolling();
              previewMut.reset();
              commitMut.reset();
            }}
            className="px-4 py-2 text-sm border border-ink-line rounded hover:bg-slate-50"
          >
            Загрузить ещё
          </button>
        </div>
      </div>
    );
  }

  // ── Preview screen ─────────────────────────────────────────────────────────

  if (!preview) return null;

  return (
    <div className="p-5 max-w-[820px] mx-auto space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {readOnly ? "Прошлый предпросмотр (только чтение)" : "Предпросмотр"}
          </h2>
          <div className="text-xs text-ink-mute mt-0.5">
            фактов: {preview.facts.length} · пропущено LayerGuard: {preview.skipped.length}
          </div>
        </div>
        <button
          onClick={() => {
            if (readOnly || reopened) {
              setReadOnly(false);
              setReopened(false);
              setPreview(null);
              setScreen("history");
            } else {
              setScreen("input");
              previewMut.reset();
            }
          }}
          className="text-xs text-ink-mute hover:text-ink"
        >
          ← Назад
        </button>
      </div>

      {readOnly && (
        <div className="bg-slate-100 border border-slate-300 rounded-lg p-3 text-sm text-slate-700">
          <span className="font-medium">Внесено</span>:{" "}
          {preview.confirmed_at && new Date(preview.confirmed_at).toLocaleString()} —
          режим просмотра. Правки и повторное внесение отключены.
        </div>
      )}

      {!readOnly && reopened && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
          <span className="font-medium">Незакоммиченный прогон из истории.</span>{" "}
          Проверьте факты и сохраните в матрицу — кэш транскрипта уже есть, заново
          распознавать не нужно.
        </div>
      )}

      {/* Video meta */}
      <div className="bg-white rounded-lg border border-ink-line p-5 space-y-1 text-sm">
        <div className="font-medium">{preview.meta.title}</div>
        <div className="text-xs text-ink-mute">
          {preview.meta.channel_name} · {fmtDuration(preview.meta.duration_sec)}
          {preview.meta.view_count != null &&
            ` · ${preview.meta.view_count.toLocaleString()} просмотров`}
          {preview.meta.like_count != null &&
            ` · ${preview.meta.like_count.toLocaleString()} лайков`}
          {preview.meta.upload_date && ` · ${preview.meta.upload_date}`}
          {preview.from_cache && " · транскрипт из кэша"}
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

      {/* Обзор эпизода — read-only ориентировка перед разбором фактов */}
      <EpisodeOverview
        clientId={clientId}
        url={preview.meta.canonical_url}
        speakerEntityId={effectiveSpeaker}
      />

      {/* Orientation brief — paragraph + per-cell coverage */}
      {(preview.video_brief || (preview.cell_briefs && Object.keys(preview.cell_briefs).length > 0)) && (
        <div className="bg-white rounded-lg border border-ink-line p-5 space-y-3">
          {preview.video_brief && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1">
                Краткая сводка
              </div>
              <div className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
                {preview.video_brief}
              </div>
            </div>
          )}
          {preview.cell_briefs && Object.keys(preview.cell_briefs).length > 0 && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-ink-mute mb-1">
                Покрытие ({Object.keys(preview.cell_briefs).length} ячеек)
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
            Оригинальное описание видео ({preview.meta.description.length} символов)
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
            ⚠ Не обработано чанков: {preview.stats.chunks_failed} из {preview.stats.chunks_total ?? "?"}
          </div>
          <div className="text-xs mt-1">
            Часть 15-минутных окон не дала фактов: LLM вернул пустой или нечитаемый ответ.
            Запустите предпросмотр ещё раз — транскрипт уже в кэше.
          </div>
        </div>
      )}

      {/* Parser notes */}
      {preview.notes.length > 0 && (
        <details className="text-xs text-ink-mute">
          <summary className="cursor-pointer hover:text-ink">
            Заметки парсера: {preview.notes.length}
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
            Факты ({preview.facts.length})
          </div>
          {!readOnly && (
            <div className="flex items-center gap-2 text-[10px]">
              <button
                onClick={() => setSelected(new Set(preview.facts.map((_, i) => i)))}
                className="text-ink-mute hover:text-ink"
              >
                выбрать всё
              </button>
              <span className="text-slate-300">·</span>
              <button
                onClick={() => setSelected(new Set())}
                className="text-ink-mute hover:text-ink"
                disabled={selected.size === 0}
              >
                сбросить
              </button>
            </div>
          )}
        </div>

        {/* Bulk-actions toolbar */}
        {!readOnly && selected.size > 0 && (
          <div className="sticky top-0 z-10 mb-3 bg-amber-50 border border-amber-300 rounded-lg p-3 flex flex-wrap items-center gap-2 text-xs shadow-sm">
            <span className="font-medium text-amber-900">
              выбрано: {selected.size}
            </span>
            <div className="h-4 w-px bg-amber-300" />
            <button
              onClick={bulkDrop}
              className="px-2 py-1 border border-red-300 text-red-700 rounded hover:bg-red-50"
            >
              снять
            </button>
            <button
              onClick={bulkRestore}
              className="px-2 py-1 border border-emerald-300 text-emerald-700 rounded hover:bg-emerald-50"
            >
              вернуть
            </button>
            <div className="h-4 w-px bg-amber-300" />
            <span className="text-amber-900">флаг →</span>
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
            <span className="text-amber-900">перенести →</span>
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
              <option value="" disabled>позиция…</option>
              {subsectionOptions.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => setSelected(new Set())}
              className="ml-auto text-[10px] text-amber-900 hover:text-amber-700"
            >
              ✕ сбросить
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
              clientId={clientId}
              sourceTitle={preview.meta.title}
              dupHint={hintByIdx.get(idx)}
              onJumpToCell={onJumpToCell}
            />
          ))}
        </div>
      </div>

      {/* Skipped facts (LayerGuard) */}
      {preview.skipped.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
            Пропущено LayerGuard ({preview.skipped.length})
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
                clientId={clientId}
                sourceTitle={preview.meta.title}
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
        {/* Interviewee: 1 founder → auto; >1 → must pick who this interview is with. */}
        {founders.length > 1 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-ink-mute">🗣 С кем интервью?</span>
            <select
              value={effectiveSpeaker ?? ""}
              onChange={(e) => setSpeakerId(e.target.value ? Number(e.target.value) : null)}
              className={`text-sm border rounded px-2 py-1 bg-white ${effectiveSpeaker ? "border-ink-line text-ink" : "border-amber-300 text-amber-700"}`}
            >
              <option value="">— выберите фаундера —</option>
              {founders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            {!effectiveSpeaker && <span className="text-[11px] text-amber-600">факты получат имя спикера</span>}
          </div>
        )}
        {founders.length === 1 && (
          <div className="text-[11px] text-ink-mute">🗣 Спикер: {founders[0].name} (подставится автоматически)</div>
        )}
        <div className="flex items-center gap-3">
          <input
            type="email"
            placeholder="ваш@email.com"
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
              ? "Сохраняю…"
              : `Сохранить факты в матрицу (${keptCount})`}
          </button>
        </div>
        {keptCount === 0 && (
          <div className="text-xs text-red-600">Все факты сняты — нечего сохранять</div>
        )}
        {commitMut.isError && (
          <div className="text-xs text-red-600">{String(commitMut.error)}</div>
        )}
      </div>
      )}
    </div>
  );
}

// ── Чип «возможный дубль» ─────────────────────────────────────────────────────
// Показываем то, на что факт похож, и даём не брать его. Склейка здесь невозможна
// по построению: факта превью в базе ещё нет, а склеивать можно только сохранённые
// (см. «Проверку фактов» — там же это и делается после коммита).

function DupHintChip({ hint, onDrop, onJumpToCell }: {
  hint: DuplicateHint;
  onDrop: () => void;
  onJumpToCell?: (sid: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="text-xs">
      <button
        onClick={() => setOpen(v => !v)}
        className="px-1.5 py-0.5 rounded border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
      >
        похоже на существующий факт
      </button>
      {open && (
        <div className="mt-1.5 border-l-2 border-amber-300 pl-2 space-y-1">
          <div className="text-slate-600">{hint.fact.text}</div>
          <div className="flex gap-3">
            {onJumpToCell && (
              <button onClick={() => onJumpToCell(hint.fact.subsection_id)}
                      className="text-blue-600 hover:underline">
                открыть в матрице
              </button>
            )}
            <button onClick={onDrop} className="text-amber-800 hover:underline">
              не брать этот факт
            </button>
          </div>
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
  clientId: string;
  sourceTitle?: string;
  /** When set, the timecode renders as a button that seeks an audio player. */
  onSeek?: (sec: number) => void;
  /** Похожий факт уже в матрице — жёлтый чип. Ничего не блокирует. */
  dupHint?: DuplicateHint;
  onJumpToCell?: (sid: string) => void;
}

export function FactCard({ fact, edit, dropped, readOnly, selected, onToggleSelect, subsectionOptions, onToggleDrop, onEdit, clientId, sourceTitle, onSeek, dupHint, onJumpToCell }: FactCardProps) {
  const [editing, setEditing] = useState(false);
  const effectiveTextRu = edit?.text_ru ?? (fact.text_ru || fact.text);
  const effectiveSid = edit?.subsection_id ?? fact.subsection_id;
  const effectiveFlag = (edit?.flag ?? fact.flag) as string;
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
        <div className="flex flex-col items-center gap-1 shrink-0 mt-0.5">
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border text-center ${
            edit?.subsection_id
              ? "bg-amber-50 border-amber-200 text-amber-700"
              : "bg-slate-100 border-slate-200 text-slate-600"
          }`}>
            {effectiveSid}
          </span>
          <FlagDot flag={effectiveFlag} />
        </div>

        {/* Center: content */}
        <div className="flex-1 min-w-0 space-y-1.5">
          {!editing ? (
            <>
              <div className={`font-medium text-slate-800 ${dropped ? "line-through" : ""}`}>
                {displayRu}
                {isEdited && <span className="ml-1 text-[10px] text-amber-600">(изменено)</span>}
              </div>
              {displayEn && displayEn !== displayRu && (
                <div className="text-xs text-slate-500 italic">{displayEn}</div>
              )}
              {displayQuote && (
                <div className="text-xs text-slate-400 border-l-2 border-slate-200 pl-2 line-clamp-3">
                  "{displayQuote}"
                </div>
              )}
              {dupHint && !dropped && (
                <DupHintChip hint={dupHint} onDrop={onToggleDrop} onJumpToCell={onJumpToCell} />
              )}
              {effectiveFlag === "red" && (
                fact.rationale
                  ? <div className="text-xs border-l-2 border-flag-red/60 text-flag-red pl-2 leading-snug">
                      <span className="font-medium uppercase tracking-wide text-[10px] mr-1">риск:</span>
                      {fact.rationale}
                    </div>
                  : <div className="text-xs italic text-amber-600">⚠ Риск не указан</div>
              )}
              {effectiveFlag === "grey" && fact.rationale && (
                <div className="text-xs border-l-2 border-slate-300 text-ink-mute pl-2 leading-snug">
                  <span className="font-medium uppercase tracking-wide text-[10px] mr-1">пробел:</span>
                  {fact.rationale}
                </div>
              )}
              <SourceLine
                client_id={clientId}
                channel="online_interview"
                source_url={fact.source_url}
                source_title={sourceTitle}
                timestamp_sec={fact.snippet_start_sec}
                onSeek={onSeek}
              />
              {isEdited && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => onEdit({ text_ru: undefined, subsection_id: undefined, flag: undefined })}
                    className="text-[10px] text-amber-600 hover:underline"
                  >
                    revert edits
                  </button>
                </div>
              )}
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
  clientId: string;
  sourceTitle?: string;
  /** When set, the timecode renders as a button that seeks an audio player. */
  onSeek?: (sec: number) => void;
}

export function SkippedCard({ skipped, edit, overridden, readOnly, subsectionOptions, onToggleOverride, onEdit, clientId, sourceTitle, onSeek }: SkippedCardProps) {
  const [editing, setEditing] = useState(false);
  const effectiveTextRu = edit?.text_ru ?? (skipped.text_ru || skipped.text);
  const effectiveSid = edit?.subsection_id ?? skipped.subsection_id;
  const effectiveFlag = (edit?.flag ?? skipped.flag ?? "green") as string;
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
                {isEdited && <span className="ml-1 text-[10px] text-amber-600">(изменено)</span>}
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
              {(skipped.source_url || onSeek) && (
                <SourceLine
                  client_id={clientId}
                  channel="online_interview"
                  source_url={skipped.source_url}
                  source_title={sourceTitle}
                  timestamp_sec={skipped.snippet_start_sec}
                  onSeek={onSeek}
                />
              )}
              {isEdited && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => onEdit({ text_ru: undefined, subsection_id: undefined, flag: undefined })}
                    className="text-[10px] text-amber-600 hover:underline"
                  >
                    revert edits
                  </button>
                </div>
              )}
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
