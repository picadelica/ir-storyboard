import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type { DuplicateHint, Layer, YouTubePreviewResult } from "../types";
import {
  FactCard, SkippedCard, fmtDuration, editIsEmpty, type FactEdit,
} from "./IngestYouTube";
import AudioSourcePanel, { type AudioSourceHandle } from "./AudioSourcePanel";

const ALLOWED_EXT = [".m4a", ".mp3", ".wav", ".ogg", ".aac"];
const MAX_BYTES = 500 * 1024 * 1024;

// localStorage: per-client активный аудио-джоб, чтобы переживать unmount при
// смене вкладки и перезагрузку страницы. Чистится при done/error/404.
const audioJobKey = (clientId: string) => `audio_job:${clientId}`;
type StoredAudioJob = {
  job_id: string;
  started_at: number;
  title: string;
  file_name: string;
};

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
  layers?: Layer[];
}

export default function IngestAudio({ clientId, onJumpToCell, layers }: Props) {
  const subsectionOptions = (layers ?? []).flatMap(L =>
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${subsectionNameRu(s.id, s.name)} (${layerNameRu(L.id, L.name)})` }))
  );

  const [screen, setScreen] = useState<"input" | "preview" | "done">("input");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<YouTubePreviewResult | null>(null);
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [overrides, setOverrides] = useState<Set<number>>(new Set());
  const [factEdits, setFactEdits] = useState<Record<number, FactEdit>>({});
  const [skippedEdits, setSkippedEdits] = useState<Record<number, FactEdit>>({});
  const [expertEmail, setExpertEmail] = useState("");
  const [jobStatus, setJobStatus] = useState<string>("");
  const [jobError, setJobError] = useState<string>("");
  const [jobStage, setJobStage] = useState<string>("");
  const [jobStartedAt, setJobStartedAt] = useState<number | null>(null);
  const [, forceTick] = useState(0); // тикер для elapsed-счётчика

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioPanelRef = useRef<AudioSourceHandle | null>(null);
  const qc = useQueryClient();

  const seekTo = (sec: number) => audioPanelRef.current?.seek(sec);

  // Подсказка «возможный дубль» — та же, что в YouTube-превью: похожие активные
  // факты той же ячейки. Ничего не блокирует.
  const dupHints = useQuery<DuplicateHint[]>({
    queryKey: ["dup-hints", clientId, preview?.preview_id],
    queryFn: () => api.duplicateHints(
      clientId,
      (preview?.facts ?? []).map(f => ({ subsection_id: f.subsection_id, text: f.text_ru || f.text })),
    ),
    enabled: Boolean(preview?.preview_id && (preview?.facts ?? []).length > 0),
  });
  const hintByIdx = new Map((dupHints.data ?? []).map(h => [h.idx, h]));

  // Секундный тик, пока идёт обработка — чтобы elapsed обновлялся
  useEffect(() => {
    if (jobStatus !== "processing") return;
    const t = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [jobStatus]);

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }
  useEffect(() => () => stopPolling(), []);

  // Запускает polling статуса джоба (общий код для свежезапущенного
  // и восстановленного из localStorage). Очищает localStorage на done/error/404.
  function startPolling(jobId: string) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.audioPreviewStatus(clientId, jobId);
        setJobStatus(status.status);
        if (status.stage) setJobStage(status.stage);
        if (status.status === "done" && status.result) {
          stopPolling();
          localStorage.removeItem(audioJobKey(clientId));
          setPreview(status.result);
          setDropped(new Set());
          setOverrides(new Set());
          setFactEdits({});
          setSkippedEdits({});
          setScreen("preview");
        } else if (status.status === "error") {
          stopPolling();
          localStorage.removeItem(audioJobKey(clientId));
          setJobError(status.error || "что-то пошло не так");
        }
      } catch (e) {
        // 404 = бэк потерял джоб (рестарт контейнера). Сбрасываем UI в input.
        stopPolling();
        localStorage.removeItem(audioJobKey(clientId));
        setJobStatus("");
        setJobError(
          e instanceof Error && /404/.test(e.message)
            ? "Задача потеряна (backend перезапустился). Загрузите файл заново."
            : "Связь с сервером прервана. Попробуйте ещё раз."
        );
      }
    }, 5000);
  }

  // Восстановление активного джоба при mount (включая после reload и
  // после смены вкладки, т.к. в App.tsx стоит key={clientId} → каждый
  // клиент получает свой lifecycle и свой ключ в localStorage).
  useEffect(() => {
    const raw = localStorage.getItem(audioJobKey(clientId));
    if (!raw) return;
    let saved: StoredAudioJob;
    try {
      saved = JSON.parse(raw) as StoredAudioJob;
    } catch {
      localStorage.removeItem(audioJobKey(clientId));
      return;
    }
    if (!saved.job_id) {
      localStorage.removeItem(audioJobKey(clientId));
      return;
    }
    setJobStatus("processing");
    setJobError("");
    setJobStage("восстановление состояния…");
    setJobStartedAt(saved.started_at || Date.now());
    if (saved.title) setTitle(saved.title);
    startPolling(saved.job_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fileError = (() => {
    if (!file) return "";
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) return `Неподдерживаемый формат ${ext}. Можно: ${ALLOWED_EXT.join(", ")}`;
    if (file.size > MAX_BYTES) return "Файл больше 500 MB";
    return "";
  })();

  const previewMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("No file");
      return api.audioPreviewStart(clientId, file, title.trim() || undefined);
    },
    onSuccess: (job) => {
      const startedAt = Date.now();
      setJobStatus("processing");
      setJobError("");
      setJobStage("загрузка принята, запуск пайплайна…");
      setJobStartedAt(startedAt);
      localStorage.setItem(audioJobKey(clientId), JSON.stringify({
        job_id: job.job_id,
        started_at: startedAt,
        title: title.trim() || (file?.name ?? ""),
        file_name: file?.name ?? "",
      } satisfies StoredAudioJob));
      startPolling(job.job_id);
    },
    onError: (e) => setJobError(e instanceof Error ? e.message : String(e)),
  });

  const commitMut = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("No preview");
      const accepted = preview.facts
        .map((_, i) => i)
        .filter((i) => !dropped.has(i));

      const ov: Array<Record<string, unknown>> = [];
      for (const i of accepted) {
        const e = factEdits[i];
        if (!editIsEmpty(e)) ov.push({ kind: "fact", idx: i, ...e });
      }
      for (const i of Array.from(overrides)) {
        const e = skippedEdits[i] || {};
        ov.push({ kind: "skipped", idx: i, force_keep: true, ...e });
      }

      return api.audioCommit(
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
      setScreen("done");
    },
  });

  const keptCount = preview
    ? preview.facts.filter((_, i) => !dropped.has(i)).length
    : 0;

  function updateEdit(
    setter: (updater: (prev: Record<number, FactEdit>) => Record<number, FactEdit>) => void,
    idx: number,
    patch: FactEdit,
  ) {
    setter((prev) => {
      const next = { ...prev };
      const merged = { ...next[idx], ...patch } as Record<string, unknown>;
      Object.keys(merged).forEach((k) => {
        const v = merged[k];
        if (v === "" || v === undefined || v === null) delete merged[k];
      });
      if (Object.keys(merged).length === 0) delete next[idx]; else next[idx] = merged as FactEdit;
      return next;
    });
  }

  // ── Input screen ─────────────────────────────────────────────────────────

  if (screen === "input") {
    const processing = previewMut.isPending || jobStatus === "processing";
    return (
      <div className="p-5 max-w-[820px] mx-auto space-y-4">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-ink">Загрузка аудиозаписи</h2>
          <p className="text-sm text-ink-mute">
            Загрузите аудиофайл, проверьте извлечённые факты и внесите их в матрицу.
          </p>
        </div>

        <div className="bg-white rounded-lg border border-ink-line p-5 space-y-4">
          <div className="space-y-2">
            <label className="block text-xs font-medium text-ink-mute">
              Аудиофайл ({ALLOWED_EXT.join(" / ")}, до 500 MB)
            </label>
            <input
              type="file"
              accept={ALLOWED_EXT.join(",")}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink-mute file:mr-3 file:px-3 file:py-1.5 file:text-sm file:font-medium file:border file:border-ink-line file:rounded-xl file:bg-white file:text-ink hover:file:bg-slate-50 file:cursor-pointer"
            />
            {fileError && <div className="text-xs text-red-600">{fileError}</div>}
          </div>

          <div className="space-y-2">
            <label className="block text-xs font-medium text-ink-mute">
              Название (опционально — по умолчанию имя файла)
            </label>
            <input
              type="text"
              placeholder='например «Интервью с фаундером 2026-06-01»'
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full text-sm border border-ink-line rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-ink"
            />
          </div>

          <div className="space-y-3">
            <button
              onClick={() => previewMut.mutate()}
              disabled={!file || !!fileError || processing}
              className={`px-4 py-2 text-sm rounded-xl font-medium transition ${
                !file || fileError || processing
                  ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                  : "bg-ink text-white hover:bg-ink/90"
              }`}
            >
              {processing ? "Обрабатываю…" : "Предпросмотр"}
            </button>
            {processing && (
              <div className="rounded-xl border border-ink-line bg-[#fbfbf7] p-3 text-xs text-ink-mute space-y-1">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
                  <span className="font-medium">
                    {jobStage || "Запущено в фоне — обрабатываем…"}
                  </span>
                  {jobStartedAt && (
                    <span className="font-mono text-[10px] text-slate-400">
                      {Math.floor((Date.now() - jobStartedAt) / 60000)}:
                      {String(Math.floor(((Date.now() - jobStartedAt) / 1000) % 60)).padStart(2, "0")}
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-slate-400">
                  Этапы: нарезка → транскрибирование чанков → извлечение фактов.
                  Для часовой записи ~5–15 мин. Повторная загрузка того же файла
                  бесплатна — транскрипт кэшируется.
                </div>
              </div>
            )}
            {(jobStatus === "error" || jobError) && !processing && (
              <div className="text-sm text-red-600 bg-red-50 rounded-xl p-3">
                Ошибка: {jobError || "что-то пошло не так"}
              </div>
            )}
          </div>
        </div>
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
              setScreen("input");
              setPreview(null);
              setFile(null);
              setTitle("");
              setJobStatus("");
              setJobError("");
              stopPolling();
              localStorage.removeItem(audioJobKey(clientId));
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

  // canonical_url is "file://<sha[:16]>" — strip the scheme to get the sha prefix.
  const sourceSha = (preview.meta.canonical_url || "").replace(/^file:\/\//, "");

  return (
    <div className="p-5 max-w-[820px] mx-auto space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">Предпросмотр</h2>
          <div className="text-xs text-ink-mute mt-0.5">
            {preview.facts.length} фактов · {preview.skipped.length} пропущено LayerGuard
          </div>
        </div>
        <button
          onClick={() => { setScreen("input"); previewMut.reset(); setJobStatus(""); }}
          className="text-xs text-ink-mute hover:text-ink"
        >
          ← Назад
        </button>
      </div>

      {/* Audio meta */}
      <div className="bg-white rounded-lg border border-ink-line p-5 space-y-1 text-sm">
        <div className="font-medium">{preview.meta.title}</div>
        <div className="text-xs text-ink-mute">
          {preview.meta.channel_name} · {fmtDuration(preview.meta.duration_sec)}
          {preview.from_cache && " · транскрипт из кэша"}
          {preview.transcribe_cost_usd != null &&
            ` · ~$${preview.transcribe_cost_usd.toFixed(2)} (OpenAI Whisper)`}
        </div>
        <div className="text-xs text-slate-400 font-mono">{preview.meta.canonical_url}</div>
        {sourceSha && (
          <div className="pt-2">
            <AudioSourcePanel
              ref={audioPanelRef}
              clientId={clientId}
              sha={sourceSha}
              title={preview.meta.title}
            />
            <div className="text-[10px] text-slate-400 mt-1">
              Клик по таймкоду факта перематывает плеер к этому месту.
            </div>
          </div>
        )}
      </div>

      {/* Orientation brief */}
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

      {/* Chunk-failure warning */}
      {(preview.stats.chunks_failed ?? 0) > 0 && (
        <div className="bg-amber-50 border border-amber-300 rounded-lg p-3 text-sm text-amber-900">
          <div className="font-medium">
            ⚠ Не обработано чанков: {preview.stats.chunks_failed} из {preview.stats.chunks_total ?? "?"}
          </div>
          <div className="text-xs mt-1">
            Часть окон не дала фактов (LLM вернул пустой ответ). Перезапустите
            preview — транскрипт в кэше, повтор бесплатный.
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
        <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
          Факты ({preview.facts.length})
        </div>
        <div className="space-y-2">
          {preview.facts.map((fact, idx) => (
            <FactCard
              key={idx}
              fact={fact}
              edit={factEdits[idx]}
              dropped={dropped.has(idx)}
              subsectionOptions={subsectionOptions}
              onToggleDrop={() => setDropped((prev) => {
                const next = new Set(prev);
                next.has(idx) ? next.delete(idx) : next.add(idx);
                return next;
              })}
              onEdit={(patch) => updateEdit(setFactEdits, idx, patch)}
              clientId={clientId}
              sourceTitle={preview.meta.title}
              onSeek={sourceSha ? seekTo : undefined}
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
                subsectionOptions={subsectionOptions}
                clientId={clientId}
                sourceTitle={preview.meta.title}
                onToggleOverride={() => setOverrides((prev) => {
                  const next = new Set(prev);
                  next.has(idx) ? next.delete(idx) : next.add(idx);
                  return next;
                })}
                onEdit={(patch) => updateEdit(setSkippedEdits, idx, patch)}
                onSeek={sourceSha ? seekTo : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {/* Commit bar */}
      <div className="sticky bottom-0 bg-white border-t border-ink-line pt-4 pb-2 space-y-3">
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
    </div>
  );
}
