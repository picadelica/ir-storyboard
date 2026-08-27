import { useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type { FactCandidateOut, IngestPreviewOut, Layer, ResearchResult } from "../types";
import FlagDot from "./FlagDot";
import { HintTarget } from "./Hint";

type SourceStatus = "regular" | "client";
type InputMode = "link" | "file" | "text";
type FileKind = "pdf" | "text" | "document" | "audio" | "video" | "unknown";
type UrlRoute =
  | { label: string; helper: string; path: string }
  | { label: string; helper: string; action: "preview" | "search" };

type ResearchHit = ResearchResult["hits"][number];

const BLOCK_KICKER = "text-[11px] font-bold uppercase tracking-[0.18em]";
const KICKER_GREEN = "text-[#6d8d13]";
const KICKER_BLUE = "text-[#3f70b5]";
const PANEL = "rounded-lg border p-5";
const FIELD_LABEL = "text-xs font-medium text-ink-mute";
const FIELD = "w-full text-sm border border-ink-line rounded-xl bg-white focus:outline-none focus:ring-1 focus:ring-ink focus:border-ink transition";
const INPUT_FIELD = `${FIELD} h-10 px-3`;
const TEXTAREA_FIELD = `${FIELD} px-3 py-2 leading-relaxed resize-y`;
const SELECT_FIELD = "text-xs border border-ink-line rounded-xl bg-white px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-ink focus:border-ink transition";
const BUTTON_PRIMARY = "h-10 shrink-0 text-sm bg-ink text-white rounded-xl px-4 font-normal hover:opacity-90 disabled:opacity-40 transition";
const BUTTON_SECONDARY = "shrink-0 rounded-xl border border-ink-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-[#fbfbf7] disabled:opacity-40 transition";
const COMPACT_CARD = "rounded-xl border border-ink-line bg-white px-3 py-2";

interface Props {
  clientId: string;
  layers?: Layer[];
}

type PreviewRow = FactCandidateOut & {
  checked: boolean;
  subsection_id: string;
  flag: "green" | "red" | "grey";
  source_title: string;
  source_url: string;
  channel: string;
};

const statusCopy: Record<SourceStatus, { title: string; body: string }> = {
  regular: {
    title: "Обычный материал",
    body: "Обычные факты: веб, документы, интервью и медиа.",
  },
  client: {
    title: "От клиента",
    body: "Обязательные факты с синим приоритетом must-have.",
  },
};

const methodCopy: Record<InputMode, { icon: string; title: string; description: string }> = {
  link: {
    icon: "↗",
    title: "Ссылка / поиск",
    description: "Вставьте URL, видео, PDF или запрос — система поймёт маршрут.",
  },
  file: {
    icon: "▣",
    title: "Файл",
    description: "Перетащите PDF, документ, текст, аудио или видео — разберём тип.",
  },
  text: {
    icon: "Aa",
    title: "Текст",
    description: "Вставьте заметки, расшифровку, ответ агента или любой фрагмент.",
  },
};

const statusAccent: Record<SourceStatus, {
  panel: string;
  border: string;
  activeCard: string;
  inactiveCard: string;
  icon: string;
  kicker: string;
  divider: string;
  drop: string;
  dropActive: string;
}> = {
  regular: {
    panel: "bg-[#fbfff2]",
    border: "border-[#d8e6b8]",
    activeCard: "border-[#98c61b]/60 bg-[#f0fadb]",
    inactiveCard: "border-[#d8e0cc] bg-white hover:-translate-y-px hover:bg-[#fbfff2] hover:border-[#98c61b]/70",
    icon: KICKER_GREEN,
    kicker: KICKER_GREEN,
    divider: "border-[#d8e6b8]",
    drop: "border-[#cfd4c6] bg-white hover:border-[#98c61b]/70 hover:bg-[#fbfff2]",
    dropActive: "border-[#98c61b] bg-[#f0fadb]",
  },
  client: {
    panel: "bg-[#f3f8ff]",
    border: "border-[#bfd7f5]",
    activeCard: "border-flag-blue/45 bg-flag-blue/10",
    inactiveCard: "border-[#d2dbe8] bg-white hover:-translate-y-px hover:bg-[#f3f8ff] hover:border-flag-blue/45",
    icon: "text-flag-blue",
    kicker: KICKER_BLUE,
    divider: "border-[#bfd7f5]",
    drop: "border-[#c8d4e4] bg-white hover:border-flag-blue/50 hover:bg-[#f3f8ff]",
    dropActive: "border-flag-blue bg-flag-blue/10",
  },
};

function isYouTubeUrl(value: string) {
  return /(?:youtube\.com|youtu\.be)\b/i.test(value);
}

function looksLikePdfUrl(value: string) {
  return /\.pdf(?:[?#].*)?$/i.test(value);
}

function looksLikeAudioVideoUrl(value: string) {
  return /\.(?:mp3|wav|m4a|aac|flac|ogg|mp4|mov|webm|mkv)(?:[?#].*)?$/i.test(value);
}

function looksLikeHttpUrl(value: string) {
  return /^https?:\/\//i.test(value.trim());
}

function fileKind(file: File): FileKind {
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  if (type.includes("pdf") || name.endsWith(".pdf")) return "pdf";
  if (/\.(txt|md)$/i.test(name) || type.startsWith("text/")) return "text";
  if (/\.(docx|rtf)$/i.test(name)) return "document";
  if (type.startsWith("audio/") || /\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(name)) return "audio";
  if (type.startsWith("video/") || /\.(mp4|mov|webm|mkv)$/i.test(name)) return "video";
  return "unknown";
}

function fileLabel(kind: FileKind) {
  return kind === "pdf" ? "PDF"
    : kind === "text" ? "Текстовый файл"
    : kind === "document" ? "Документ"
    : kind === "audio" ? "Аудио"
    : kind === "video" ? "Видео-файл"
    : "Неизвестный тип";
}

function MethodIcon({ value }: { value: InputMode }) {
  const p = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (value === "link") {
    return (
      <svg {...p} aria-hidden="true">
        <path d="M10 13a5 5 0 0 0 7.07 0l2.12-2.12a5 5 0 0 0-7.07-7.07L11 4.93" />
        <path d="M14 11a5 5 0 0 0-7.07 0L4.81 13.12a5 5 0 0 0 7.07 7.07L13 19.07" />
      </svg>
    );
  }
  if (value === "file") {
    return (
      <svg {...p} aria-hidden="true">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
        <path d="M8 13h8" />
        <path d="M8 17h5" />
      </svg>
    );
  }
  return <span className="text-[12px] font-bold leading-none">Aa</span>;
}

function rowsFromPreview(preview: IngestPreviewOut): PreviewRow[] {
  return preview.candidates.map(c => ({
    ...c,
    checked: !!c.suggested_subsection_id,
    subsection_id: c.suggested_subsection_id || "",
    flag: c.suggested_flag,
    source_title: preview.source_title,
    source_url: preview.source_url,
    channel: preview.channel,
  }));
}

export default function AddDataHub({ clientId, layers }: Props) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<SourceStatus>("regular");
  const [mode, setMode] = useState<InputMode>("link");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<PreviewRow[] | null>(null);
  const [searchHits, setSearchHits] = useState<ResearchHit[] | null>(null);
  const [previewMeta, setPreviewMeta] = useState<{ title: string; status: SourceStatus } | null>(null);
  const [done, setDone] = useState<{ written: number; skipped: number } | null>(null);
  const clientMode = status === "client";

  const subsectionOptions = (layers ?? []).flatMap(L =>
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${subsectionNameRu(s.id, s.name)} (${layerNameRu(L.id, L.name)})` }))
  );

  const urlRoute = useMemo<UrlRoute | null>(() => {
    const value = url.trim();
    if (!value) return null;
    if (!looksLikeHttpUrl(value)) {
      return {
        label: "Поисковый запрос",
        helper: "Найдём источники по этому запросу и покажем их здесь же. Подходящий результат можно будет сразу разобрать.",
        action: "search" as const,
      };
    }
    if (isYouTubeUrl(value)) {
      return {
        label: "Видео",
        helper: "Похоже на YouTube-ссылку — откроем видео-обработчик с уже вставленным URL.",
        path: `/clients/${clientId}/youtube?url=${encodeURIComponent(value)}`,
      };
    }
    if (looksLikePdfUrl(value)) {
      return {
        label: clientMode ? "PDF от клиента" : "PDF по ссылке",
        helper: "Определили PDF — скачаем файл, разберём его и покажем факты перед сохранением.",
        action: "preview" as const,
      };
    }
    if (looksLikeAudioVideoUrl(value)) {
      return {
        label: "Аудио / видео файл",
        helper: "Похоже на прямую ссылку на медиафайл. Пока откроем аудио-обработчик; скачивание по URL добавим отдельным backend-шагом.",
        path: `/clients/${clientId}/audio`,
      };
    }
    return {
      label: "Веб-источник",
      helper: "Похоже на обычную страницу — скачаем текст и покажем предпросмотр фактов.",
      action: "preview" as const,
    };
  }, [clientId, clientMode, url]);

  const filePlan = files.map(file => ({ file, kind: fileKind(file), label: fileLabel(fileKind(file)) }));
  const previewableFiles = filePlan.filter(x => x.kind === "pdf" || x.kind === "text" || x.kind === "document");
  const mediaFiles = filePlan.filter(x => x.kind === "audio" || x.kind === "video");
  const legacyFiles = filePlan.filter(x => x.kind === "unknown");

  const textPreview = useMutation({
    mutationFn: () => api.universalTextPreview(clientId, {
      text,
      source_status: status,
      source_title: sourceTitle.trim() || (clientMode ? "От клиента" : "Текст"),
      source_url: "",
    }),
    onSuccess: preview => {
      setRows(rowsFromPreview(preview));
      setPreviewMeta({ title: preview.source_title, status });
      setDone(null);
    },
  });

  const urlPreview = useMutation({
    mutationFn: (targetUrl?: string) => api.universalUrlPreview(clientId, {
      url: (targetUrl ?? url).trim(),
      source_status: status,
    }),
    onSuccess: preview => {
      setRows(rowsFromPreview(preview));
      setSearchHits(null);
      setPreviewMeta({ title: preview.source_title, status });
      setDone(null);
    },
  });

  const searchSources = useMutation({
    mutationFn: () => api.research(clientId, [url.trim()]),
    onSuccess: result => {
      setSearchHits(result.hits);
      setRows(null);
      setDone(null);
    },
  });

  const filePreview = useMutation({
    mutationFn: async () => {
      const previews = await Promise.all(previewableFiles.map(({ file }) => api.universalFilePreview(clientId, file, status)));
      const allRows = previews.flatMap(rowsFromPreview);
      const title = previews.length === 1 ? previews[0].source_title : `${previews.length} файлов`;
      return { title, rows: allRows };
    },
    onSuccess: result => {
      setRows(result.rows);
      setPreviewMeta({ title: result.title, status });
      setDone(null);
    },
  });

  const commit = useMutation({
    mutationFn: async () => {
      const selected = (rows ?? []).filter(r => r.checked && r.text.trim() && r.subsection_id);
      if (clientMode) {
        return api.ingestClientFacts(clientId, previewMeta?.title || "От клиента", selected.map(r => ({
          text: r.text,
          subsection_id: r.subsection_id,
          flag: r.flag,
          rationale: r.rationale,
        })));
      }
      return api.ingestConfirm(clientId, selected.map(r => ({
        text: r.text,
        subsection_id: r.subsection_id,
        flag: r.flag,
        channel: r.channel,
        source_url: r.source_url,
        source_title: r.source_title,
        evidence_snippet: r.text,
        confidence: r.confidence,
        rationale: r.rationale || undefined,
      })));
    },
    onSuccess: res => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      qc.invalidateQueries({ queryKey: ["work-items", clientId] });
      setDone({ written: res.written.length, skipped: res.skipped });
      setRows(null);
    },
  });

  const setRow = (idx: number, patch: Partial<PreviewRow>) =>
    setRows(current => current?.map((row, i) => i === idx ? { ...row, ...patch } : row) ?? null);

  const fileKey = (file: File) => `${file.name}::${file.size}::${file.lastModified}`;
  const onDropFiles = (incoming: FileList | null) => {
    const next = Array.from(incoming ?? []);
    if (next.length) {
      setFiles(current => {
        const byKey = new Map(current.map(file => [fileKey(file), file]));
        for (const file of next) byKey.set(fileKey(file), file);
        return Array.from(byKey.values());
      });
      setRows(null);
      setSearchHits(null);
      setDone(null);
    }
  };

  const selectedCount = (rows ?? []).filter(r => r.checked && r.subsection_id).length;
  const accent = statusAccent[status];
  const runUrlAction = () => {
    if (!urlRoute) return;
    if ("path" in urlRoute) {
      nav(urlRoute.path);
    } else if (urlRoute.action === "search") {
      searchSources.mutate();
    } else {
      urlPreview.mutate(undefined);
    }
  };

  const previewSearchHit = (hit: ResearchHit) => {
    setUrl(hit.url);
    urlPreview.mutate(hit.url);
  };

  return (
    <div className="p-5 max-w-[820px] mx-auto flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Добавить данные</h2>
          <p className="text-[13px] text-ink-mute mt-0.5">
            Один вход для материалов: выберите формат, статус источника и проверьте факты перед записью в матрицу.
          </p>
        </div>
      </div>

      <section className={`${PANEL} border-ink-line bg-white py-4`}>
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className={`${BLOCK_KICKER} ${accent.kicker}`}>
              Статус источника
            </div>
            <div className="mt-0.5 text-xs text-ink-mute">
              {statusCopy[status].body}
            </div>
          </div>
          <HintTarget
            title="Статус источника"
            body={"Обычный — материал из внешних источников или ваших рабочих заметок.\nОт клиента — обязательные факты, которые маркируются синим приоритетом must-have."}
          >
            <div className="relative shrink-0 inline-grid grid-cols-2 rounded-full border border-ink-line bg-[#f4f5ef] p-1 overflow-hidden">
              <span
                className={`absolute left-1 top-1 h-8 w-[calc(50%-0.25rem)] rounded-full shadow-sm transition-transform duration-300 ease-out ${
                  status === "client" ? "translate-x-full bg-[#dcecff]" : "translate-x-0 bg-[#e6f4c6]"
                }`}
              />
              {(["regular", "client"] as SourceStatus[]).map(value => {
                const active = status === value;
                return (
                  <button
                    key={value}
                    onClick={() => { setStatus(value); setRows(null); setSearchHits(null); setDone(null); }}
                    className={`relative z-10 h-8 rounded-full px-3 text-xs font-semibold transition-colors duration-200 ${
                      active
                        ? value === "client"
                          ? "text-[#23466f]"
                          : "text-[#40551f]"
                        : "text-ink-mute hover:text-ink"
                    }`}
                  >
                    {value === "regular" ? "Обычный" : "От клиента"}
                  </button>
                );
              })}
            </div>
          </HintTarget>
        </div>
      </section>

      <section className={`${PANEL} transition-colors ${accent.panel} ${accent.border} space-y-4`}>
        <div>
          <div className={`${BLOCK_KICKER} ${accent.kicker} mb-1.5`}>
            Быстрое добавление
          </div>
          <div className="text-sm font-semibold text-ink">Что у вас есть?</div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {(["link", "file", "text"] as InputMode[]).map(value => (
            <button
              key={value}
              onClick={() => { setMode(value); setRows(null); setSearchHits(null); setDone(null); }}
              className={`group min-h-[104px] rounded-2xl border px-3 py-3 text-left transition flex items-start ${
                mode === value
                  ? accent.activeCard
                  : accent.inactiveCard
              }`}
            >
              <div className="flex items-start gap-3 w-full">
                <span className={`h-7 w-7 shrink-0 rounded-xl bg-white border border-ink-line grid place-items-center text-[11px] font-bold ${accent.icon}`}>
                  <MethodIcon value={value} />
                </span>
                <span className="min-w-0">
                  <span className="block min-h-7 text-sm font-semibold leading-7 text-ink">{methodCopy[value].title}</span>
                  <span className="line-clamp-3 block mt-1 text-[10.5px] leading-[1.18] text-ink-mute">{methodCopy[value].description}</span>
                </span>
              </div>
            </button>
          ))}
        </div>

        <div className={`border-t pt-4 ${accent.divider}`}>
        {mode === "link" && (
          <div className="space-y-3">
            <div className="flex items-end gap-3">
              <label className="min-w-0 flex-1 space-y-1.5">
                <span className={FIELD_LABEL}>Ссылка или запрос</span>
                <input
                  type="text"
                  value={url}
                  onChange={e => { setUrl(e.target.value); setRows(null); setSearchHits(null); setDone(null); }}
                  onKeyDown={e => { if (e.key === "Enter") runUrlAction(); }}
                  placeholder="https://site.com/article или deeptech founder interview"
                  className={INPUT_FIELD}
                />
              </label>
              <button
                onClick={runUrlAction}
                disabled={!urlRoute || urlPreview.isPending || searchSources.isPending}
                className={BUTTON_PRIMARY}
              >
                {searchSources.isPending ? "Ищу…"
                  : urlPreview.isPending ? "Разбираю…"
                  : urlRoute && "path" in urlRoute ? "Продолжить"
                  : urlRoute?.action === "search" ? "Найти"
                  : "Разобрать"}
              </button>
            </div>
            <RouteHint tone={status} title={urlRoute?.label ?? "Жду ссылку или запрос"} body={urlRoute?.helper ?? "Вставьте URL или поисковую фразу — здесь появится предполагаемый тип обработки."} />
            {urlPreview.isError && <div className="text-sm text-flag-red">{(urlPreview.error as Error).message}</div>}
            {searchSources.isError && <div className="text-sm text-flag-red">{(searchSources.error as Error).message}</div>}
            {searchHits && (
              <div className="space-y-2">
                <div className="text-xs font-semibold text-ink">Найденные источники</div>
                {searchHits.length === 0 ? (
                  <RouteHint tone={status} title="Источники не найдены" body="Попробуйте уточнить запрос или вставьте конкретную ссылку." />
                ) : searchHits.map((hit, i) => (
                  <div key={`${hit.url}-${i}`} className={COMPACT_CARD}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <a href={hit.url} target="_blank" rel="noreferrer" className="block truncate text-sm font-semibold text-ink hover:underline">
                          {hit.title || hit.url}
                        </a>
                        <div className="mt-0.5 truncate text-[11px] text-ink-mute">{hit.url}</div>
                        {hit.snippet && (
                          <div className="mt-1 line-clamp-2 text-xs leading-snug text-ink-mute">{hit.snippet}</div>
                        )}
                      </div>
                      <button
                        onClick={() => previewSearchHit(hit)}
                        disabled={urlPreview.isPending}
                        className={BUTTON_SECONDARY}
                      >
                        Разобрать
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {mode === "file" && (
          <div className="flex flex-col gap-3">
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); onDropFiles(e.dataTransfer.files); }}
              className={`${filePlan.length > 0 ? "min-h-[116px]" : "min-h-[220px]"} rounded-2xl border border-dashed px-4 py-5 text-center cursor-pointer transition flex flex-col items-center justify-center ${
                dragOver ? accent.dropActive : accent.drop
              }`}
            >
              <input
                ref={fileRef}
                multiple
                type="file"
                className="hidden"
                onChange={e => {
                  onDropFiles(e.target.files);
                  e.currentTarget.value = "";
                }}
              />
              <div className="text-sm font-semibold text-ink">Перетащите файлы сюда или кликните для выбора</div>
              <div className="mt-1 text-xs text-ink-mute">PDF · DOCX · RTF · TXT · MD · MP3 · WAV · M4A · MP4 · MOV · WEBM</div>
              {filePlan.length > 0 && (
                <div className="mt-2 rounded-full bg-white/80 border border-ink-line px-2.5 py-1 text-[11px] font-medium text-ink-mute">
                  Выбрано файлов: {filePlan.length}
                </div>
              )}
            </div>

            {filePlan.length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="space-y-2">
                  {filePlan.map(({ file, label, kind }, i) => (
                    <div key={`${file.name}-${i}`} className={`flex items-center justify-between gap-3 ${COMPACT_CARD}`}>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-ink truncate">{file.name}</div>
                        <div className="text-xs text-ink-mute">{label} · {(file.size / 1024 / 1024).toFixed(1)} MB</div>
                      </div>
                      <span className={`shrink-0 text-[10px] px-2 py-1 rounded-full ${
                        kind === "unknown" ? "bg-flag-grey-bg text-ink-mute" : clientMode ? "bg-flag-blue/10 text-flag-blue" : "bg-[#f0fadb] text-[#40551f]"
                      }`}>
                        {kind === "pdf" || kind === "text" || kind === "document" ? "можно разобрать" : kind === "audio" || kind === "video" ? "обработка медиа" : "позже"}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="flex items-center justify-between gap-3 shrink-0">
                  <div className="flex items-center gap-2">
                    {mediaFiles.length > 0 && (
                      <button onClick={() => nav(`/clients/${clientId}/audio`)} className={BUTTON_SECONDARY}>
                        Открыть обработку медиа
                      </button>
                    )}
                  </div>
                  <button
                    onClick={() => filePreview.mutate()}
                    disabled={previewableFiles.length === 0 || filePreview.isPending}
                    className={BUTTON_PRIMARY}
                  >
                    {filePreview.isPending ? "Разбираю…" : `Разобрать ${previewableFiles.length || ""} файл(ов)`}
                  </button>
                </div>
                {legacyFiles.length > 0 && (
                  <RouteHint tone={status} title="Часть файлов пока не в универсальном вводе" body="Неизвестные типы файлов пока лучше открыть через старый «Файл / текст» или вставить содержимое в режим «Текст»." />
                )}
                {filePreview.isError && <div className="text-sm text-flag-red">{(filePreview.error as Error).message}</div>}
                  </div>
            )}
          </div>
        )}

        {mode === "text" && (
          <div className="space-y-3">
            <div className="flex items-end gap-3">
              <label className="min-w-0 flex-1 space-y-1.5">
                <span className={FIELD_LABEL}>Название источника</span>
                <input
                  value={sourceTitle}
                  onChange={e => setSourceTitle(e.target.value)}
                  placeholder={clientMode ? "От клиента" : "Текст"}
                  className={INPUT_FIELD}
                />
              </label>
              <button
                onClick={() => textPreview.mutate()}
                disabled={!text.trim() || textPreview.isPending}
                className={BUTTON_PRIMARY}
              >
                {textPreview.isPending ? "Разбираю…" : "Разобрать"}
              </button>
            </div>
            <label className="block space-y-2">
              <span className={FIELD_LABEL}>Текст</span>
              <textarea
                value={text}
                onChange={e => setText(e.target.value)}
                rows={8}
                placeholder={clientMode ? "Вставьте факты или заметки, присланные клиентом…" : "Вставьте текст отчёта, статьи, заметок или ответа агента…"}
                className={TEXTAREA_FIELD}
              />
            </label>
            <RouteHint
              tone={status}
              title={clientMode ? "Текст от клиента" : "Обычный текст"}
              body={clientMode
                ? "Разберём текст здесь, а при сохранении факты станут must-have."
                : "Разберём текст здесь и сохраним как обычные факты источника."}
            />
            {textPreview.isError && <div className="text-sm text-flag-red">{(textPreview.error as Error).message}</div>}
          </div>
        )}
        </div>
      </section>

      {rows && (
        <section className={`${PANEL} border-ink-line bg-white space-y-4`}>
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Предпросмотр фактов</h3>
              <p className="text-xs text-ink-mute mt-0.5">
                {previewMeta?.title || "Источник"} · {previewMeta?.status === "client" ? "от клиента / must-have" : "обычный материал"}
              </p>
            </div>
            <span className="text-xs text-ink-mute">{selectedCount} из {rows.length}</span>
          </div>

          {rows.length === 0 ? (
            <div className="text-sm text-ink-mute italic">Фактов не найдено. Можно попробовать другой текст или файл.</div>
          ) : (
            <div className="space-y-2">
              {rows.map((row, i) => (
                <div key={i} className={`rounded-2xl border p-4 space-y-3 ${row.checked ? "border-ink-line bg-white" : "border-ink-line bg-[#fbfbf7] opacity-70"}`}>
                  <div className="flex items-start gap-3">
                    <input type="checkbox" checked={row.checked} onChange={() => setRow(i, { checked: !row.checked })} className="mt-1.5 accent-[#98c61b]" />
                    <FlagDot flag={row.flag} className="mt-1.5 shrink-0" />
                    <textarea
                      value={row.text}
                      onChange={e => setRow(i, { text: e.target.value })}
                      rows={2}
                      className={`flex-1 ${TEXTAREA_FIELD}`}
                    />
                  </div>
                  <div className="flex items-center gap-2 pl-8">
                    <select
                      value={row.subsection_id}
                      onChange={e => setRow(i, { subsection_id: e.target.value })}
                      className={`${SELECT_FIELD} max-w-[28rem] ${row.subsection_id ? "text-ink" : "text-ink-mute"}`}
                    >
                      <option value="">— ячейка матрицы —</option>
                      {subsectionOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
                    </select>
                    <select
                      value={row.flag}
                      onChange={e => setRow(i, { flag: e.target.value as PreviewRow["flag"] })}
                      className={SELECT_FIELD}
                    >
                      <option value="green">факт</option>
                      <option value="red">риск</option>
                      <option value="grey">пробел</option>
                    </select>
                    {clientMode && <span className="text-[11px] text-flag-blue">★ от клиента</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={() => commit.mutate()}
              disabled={selectedCount === 0 || commit.isPending}
              className={`h-10 shrink-0 text-sm rounded-xl px-4 font-normal disabled:opacity-40 transition ${
                clientMode
                  ? "bg-[#dcecff] text-[#23466f] hover:bg-[#d2e5fb]"
                  : "bg-[#e6f4c6] text-[#40551f] hover:bg-[#dceeb8]"
              }`}
            >
              {commit.isPending ? "Сохраняю…" : `Сохранить ${selectedCount || ""} факт(ов)`}
            </button>
            {commit.isError && <span className="text-sm text-flag-red">{(commit.error as Error).message}</span>}
          </div>
        </section>
      )}

      {done && (
        <div className="bg-[#f0fadb] border border-[#cbd8a2] rounded-lg p-4 text-sm text-[#40551f]">
          Сохранено: {done.written}. Пропущено: {done.skipped}.
        </div>
      )}
    </div>
  );
}

function RouteHint({ title, body, tone = "neutral" }: { title: string; body: string; tone?: SourceStatus | "neutral" }) {
  const cls = tone === "regular"
    ? "border-[#d8e6b8] bg-[#fbfff2]"
    : tone === "client"
      ? "border-[#bfd7f5] bg-[#f3f8ff]"
      : "border-ink-line bg-[#fbfbf7]";
  const titleCls = tone === "regular"
    ? KICKER_GREEN
    : tone === "client"
      ? KICKER_BLUE
      : "text-ink";
  return (
    <div className={`rounded-xl border px-3 py-2 ${cls}`}>
      <div className={`text-xs font-semibold ${titleCls}`}>{title}</div>
      <div className="mt-0.5 text-xs leading-snug text-ink-mute">{body}</div>
    </div>
  );
}
