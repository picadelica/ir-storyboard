import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type { FactCandidateOut, Flag, IngestPreviewOut, ResearchHit } from "../types";

interface Props { clientId: string }

const YOUTUBE_HOST_RE = /^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)\b/i;
const TWITTER_HOST_RE = /^(?:https?:\/\/)?(?:www\.)?(?:twitter\.com|x\.com)\b/i;

function isYouTubeUrl(url: string): boolean {
  return YOUTUBE_HOST_RE.test(url.trim());
}

function isTwitterUrl(url: string): boolean {
  return TWITTER_HOST_RE.test(url.trim());
}

/** Pull the first YouTube URL out of a snippet/title (for tweets that quote a video). */
function extractYouTubeUrl(text: string): string | null {
  const m = text.match(/https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/[^\s)]+|youtu\.be\/[^\s)]+)/i);
  return m ? m[0] : null;
}

type Channel = "online_research" | "online_interview" | "archival" | "offline_interview";

const CHANNEL_COLORS: Record<string, string> = {
  online_research: "bg-blue-100 text-blue-700",
  online_interview: "bg-pink-100 text-pink-700",
  archival: "bg-amber-100 text-amber-700",
  offline_interview: "bg-slate-100 text-slate-600",
};

const FLAG_COLORS: Record<string, string> = {
  green: "bg-flag-green-bg border-flag-green/40 text-flag-green",
  red:   "bg-flag-red-bg border-flag-red/40 text-flag-red",
  grey:  "bg-flag-grey-bg border-flag-grey/40 text-flag-grey",
};

function ChannelBadge({ ch }: { ch: string }) {
  const label = ch === "online_research" ? "онлайн-исследование"
    : ch === "online_interview" ? "онлайн-интервью"
    : ch === "archival" ? "архив"
    : ch === "offline_interview" ? "офлайн-интервью"
    : ch.replace("_", " ");
  return (
    <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${CHANNEL_COLORS[ch] ?? "bg-slate-100"}`}>
      {label}
    </span>
  );
}

// ── Candidate row ────────────────────────────────────────────────────────────

interface CandidateRowProps {
  cand: FactCandidateOut;
  checked: boolean;
  onToggle: () => void;
  flag: Flag;
  onFlag: (f: Flag) => void;
  subsectionId: string;
  onSid: (s: string) => void;
  rationale: string;
  onRationale: (r: string) => void;
}

function CandidateRow({ cand, checked, onToggle, flag, onFlag, subsectionId, onSid, rationale, onRationale }: CandidateRowProps) {
  return (
    <div className={`flex gap-2 p-2.5 rounded border text-sm ${checked ? "border-blue-400 bg-blue-50" : "border-ink-line bg-white"}`}>
      <input type="checkbox" checked={checked} onChange={onToggle}
        className="mt-0.5 shrink-0 accent-blue-600" />
      <div className="flex-1 min-w-0 space-y-1">
        <div className="text-xs leading-snug">{cand.text}</div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* subsection picker */}
          <input
            value={subsectionId}
            onChange={e => onSid(e.target.value)}
            className="font-mono text-[10px] w-12 border border-ink-line rounded px-1 py-0.5"
            title="ID позиции"
          />
          <span className="text-[10px] text-ink-mute truncate">
            {layerNameRu(null, cand.suggested_layer_name)} → {subsectionNameRu(subsectionId, cand.suggested_subsection_name)}
          </span>
          {/* flag picker */}
          <select
            value={flag}
            onChange={e => onFlag(e.target.value as Flag)}
            className={`text-[10px] border rounded px-1 py-0.5 ${FLAG_COLORS[flag]}`}
          >
            <option value="green">факт</option>
            <option value="red">риск</option>
            <option value="grey">пробел</option>
          </select>
          {cand.confidence < 0.6 && (
            <span className="text-[9px] text-amber-600">уверенность {(cand.confidence * 100).toFixed(0)}%</span>
          )}
        </div>
        {cand.rationale && (
          <div className="text-[10px] text-ink-mute italic">{cand.rationale}</div>
        )}
        {flag === "red" && (
          <input
            value={rationale}
            onChange={e => onRationale(e.target.value)}
            placeholder="Проблема: что именно требует внимания (обязательно для риска)"
            className={`w-full text-[11px] border rounded px-1.5 py-0.5 ${
              rationale.trim() ? "border-ink-line" : "border-red-400"
            }`}
          />
        )}
      </div>
    </div>
  );
}

// ── Source card + preview ────────────────────────────────────────────────────

interface SourceCardProps {
  hit: ResearchHit;
  clientId: string;
  onImported: () => void;
}

function SourceCard({ hit, clientId, onImported }: SourceCardProps) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [preview, setPreview] = useState<IngestPreviewOut | null>(null);
  // Текст, доставшийся при разборе ссылки, — стартовое содержимое: аналитик
  // видит, что именно уйдёт в классификацию, и может поправить до вызова модели.
  const [customText, setCustomText] = useState(hit.text || "");
  const [showPaste, setShowPaste] = useState(Boolean(hit.text));
  const [channel, setChannel] = useState<Channel>(hit.suggested_channel as Channel || "online_research");

  const directYouTubeUrl = isYouTubeUrl(hit.url) ? hit.url : null;
  const embeddedYouTubeUrl = !directYouTubeUrl && (isTwitterUrl(hit.url) || hit.snippet)
    ? extractYouTubeUrl(`${hit.title}\n${hit.snippet}`)
    : null;
  const youtubeUrl = directYouTubeUrl || embeddedYouTubeUrl;

  function processViaYouTube() {
    if (!youtubeUrl) return;
    // Belt-and-suspenders: write the URL into the YouTube tab's localStorage
    // BEFORE navigating, so the URL is picked up even if the query-param
    // useEffect path fails (e.g. if the component was already mounted with
    // stale state from a previous session).
    try {
      const lsKey = `yt-ingest-${clientId}`;
      const prev = JSON.parse(localStorage.getItem(lsKey) || "{}");
      // Wipe any in-flight job so the prefill takes effect cleanly.
      const next = {
        ...prev,
        url: youtubeUrl,
        screen: "input",
        jobId: null,
        jobStatus: "",
        preview: null,
        factEdits: {},
        skippedEdits: {},
      };
      localStorage.setItem(lsKey, JSON.stringify(next));
    } catch {/* localStorage may be disabled — fallback to URL param below */}
    nav(`/clients/${clientId}/youtube?url=${encodeURIComponent(youtubeUrl)}`);
  }

  type RowState = { checked: boolean; flag: Flag; sid: string; rationale: string };
  const [rows, setRows] = useState<RowState[]>([]);

  const classifyMut = useMutation({
    mutationFn: async () => {
      const text = (customText || hit.snippet || "").trim();
      if (!text) {
        throw new Error("Нет текста для классификации. Откройте «Вставить полный текст» и вставьте текст статьи.");
      }
      return api.ingestPreview(clientId, {
        channel,
        source_url: hit.url,
        source_title: hit.title,
        text,
      });
    },
    onSuccess: (data) => {
      setPreview(data);
      setRows(data.candidates.map(c => ({
        checked: c.confidence >= 0.5,
        flag: c.suggested_flag as Flag,
        sid: c.suggested_subsection_id || "",
        rationale: "",
      })));
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("classifyMut error:", err);
      alert(`Классификация не удалась: ${msg}`);
    },
  });

  const confirmMut = useMutation({
    mutationFn: () => {
      const selected = preview!.candidates
        .map((c, i) => ({ c, r: rows[i] }))
        .filter(({ r }) => r.checked && r.sid);
      return api.ingestConfirm(clientId, selected.map(({ c, r }) => ({
        text: c.text,
        subsection_id: r.sid,
        flag: r.flag,
        channel,
        source_url: hit.url,
        source_title: hit.title,
        evidence_snippet: c.text,
        confidence: c.confidence,
        rationale: r.rationale.trim() || undefined,
      })));
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      qc.invalidateQueries({ queryKey: ["work-items", clientId] });
      setPreview(null);
      onImported();
      alert(`Импортировано ${res.written.length} фактов. Пропущено: ${res.skipped}.`);
    },
  });

  const checkedCount = rows.filter(r => r.checked && r.sid).length;

  return (
    <div className="bg-white border border-ink-line rounded-lg overflow-hidden">
      {/* Header */}
      <div className="p-3 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <a href={hit.url} target="_blank" rel="noreferrer"
              className="text-sm font-medium text-blue-600 hover:underline leading-snug line-clamp-2">
              {hit.title || hit.url}
            </a>
            <div className="text-xs text-ink-mute font-mono truncate mt-0.5">{hit.url}</div>
          </div>
          <ChannelBadge ch={channel} />
        </div>
        <p className="text-xs text-ink-mute leading-snug line-clamp-3">{hit.snippet}</p>

        {hit.known_source && (
          <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
            Эту ссылку уже разбирали: в матрице {hit.known_facts ?? 0} факт(ов) из неё.
            Повторный разбор не создаст дублей — одинаковые факты отсеются, — но,
            возможно, вы искали другой материал.
          </div>
        )}
        {hit.via === "" && hit.text === "" && !isYouTubeUrl(hit.url) && (
          <div className="text-[11px] text-ink-mute bg-slate-50 border border-ink-line rounded px-2 py-1">
            Текст страницы забрать не удалось (защита от ботов, JS-рендер или платный
            доступ). Открой ссылку, скопируй материал и вставь его ниже.
          </div>
        )}
        {hit.via && (
          <div className="text-[11px] text-ink-mute">
            Текст со страницы получен{hit.via === "tavily" ? " через Tavily" : " прямым запросом"}
            {customText ? ` — ${customText.length.toLocaleString("ru")} символов` : ""}.
            Проверь перед классификацией.
          </div>
        )}
      </div>

      {/* YouTube redirect banner */}
      {youtubeUrl ? (
        <div className="mx-3 mb-3 border border-pink-300 bg-pink-50 rounded p-3 space-y-2">
          <div className="flex items-start gap-2">
            <span className="text-pink-600 text-base shrink-0">🎥</span>
            <div className="text-xs text-pink-900 leading-snug flex-1">
              {directYouTubeUrl ? (
                <>Это YouTube-ссылка — текстовая классификация даст плохой результат.
                  Лучше обработать через <b>загрузку YouTube</b>: будет полный транскрипт
                  с таймкодами, факты с цитатами.</>
              ) : (
                <>В этом твите/посте есть ссылка на YouTube
                  (<code className="bg-pink-100 px-1 rounded">{youtubeUrl}</code>).
                  Рекомендуем обработать видео через <b>загрузку YouTube</b>.</>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={processViaYouTube}
            className="w-full text-xs px-3 py-1.5 bg-pink-600 text-white rounded hover:bg-pink-700"
          >
            Обработать через YouTube →
          </button>
        </div>
      ) : (
        <div className="px-3 pb-3 flex items-center gap-2 flex-wrap">
          <select
            value={channel}
            onChange={e => setChannel(e.target.value as Channel)}
            className="text-xs border border-ink-line rounded px-1.5 py-1"
          >
            <option value="online_research">онлайн-исследование</option>
            <option value="online_interview">онлайн-интервью</option>
            <option value="archival">архив</option>
          </select>
          <button
            onClick={() => setShowPaste(p => !p)}
            className="text-xs px-2 py-1 border border-ink-line rounded hover:bg-slate-50 text-ink-mute"
          >{showPaste ? "Скрыть текст" : "Вставить полный текст"}</button>
          <button
            type="button"
            onClick={() => classifyMut.mutate()}
            disabled={classifyMut.isPending}
            className="text-xs px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 ml-auto cursor-pointer"
          >{classifyMut.isPending ? "Извлекаю…" : "Извлечь факты →"}</button>
        </div>
      )}

      {showPaste && (
        <div className="px-3 pb-3">
          <textarea
            value={customText}
            onChange={e => setCustomText(e.target.value)}
            rows={6}
            placeholder="Вставь полный текст статьи / транскрипта…"
            className="w-full text-xs border border-ink-line rounded px-2 py-1.5 font-mono resize-none"
          />
        </div>
      )}

      {/* Preview candidates */}
      {preview && (
        <div className="border-t border-ink-line bg-slate-50 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase text-ink-mute tracking-wide">
              Классифицированные факты — найдено {preview.candidates.length}
            </span>
            <button
              onClick={() => setRows(r => r.map(x => ({ ...x, checked: true })))}
              className="text-[10px] text-blue-600 hover:underline"
            >Выбрать всё</button>
          </div>

          {preview.candidates.length === 0 && (
            <div className="text-xs text-ink-mute italic">
              LLM не нашёл фактов для матрицы в этом тексте.
            </div>
          )}

          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {preview.candidates.map((c, i) => (
              <CandidateRow
                key={i}
                cand={c}
                checked={rows[i]?.checked ?? false}
                onToggle={() => setRows(r => r.map((x, j) => j === i ? { ...x, checked: !x.checked } : x))}
                flag={rows[i]?.flag ?? c.suggested_flag as Flag}
                onFlag={f => setRows(r => r.map((x, j) => j === i ? { ...x, flag: f } : x))}
                subsectionId={rows[i]?.sid ?? ""}
                onSid={s => setRows(r => r.map((x, j) => j === i ? { ...x, sid: s } : x))}
                rationale={rows[i]?.rationale ?? ""}
                onRationale={r2 => setRows(r => r.map((x, j) => j === i ? { ...x, rationale: r2 } : x))}
              />
            ))}
          </div>

          {checkedCount > 0 && (
            <button
              onClick={() => confirmMut.mutate()}
              disabled={confirmMut.isPending}
              className="w-full text-sm py-2 bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50"
            >
              {confirmMut.isPending ? "Импортируем…" : `Импортировать ${checkedCount} факт(ов) →`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main view ────────────────────────────────────────────────────────────────

export default function ResearchView({ clientId }: Props) {
  const [hits, setHits] = useState<ResearchHit[]>([]);
  const [draft, setDraft] = useState("");          // editable queries, one per line
  const [generated, setGenerated] = useState(false);
  const [, setImportedCount] = useState(0);

  const [urlDraft, setUrlDraft] = useState("");

  // Разбор своей ссылки: тот же путь, что и у находки поиска, — карточка
  // добавляется в тот же список, дальше всё как обычно.
  const urlMut = useMutation({
    mutationFn: () => api.researchUrl(clientId, urlDraft.trim()),
    onSuccess: (res) => {
      setHits(prev => [
        {
          title: res.title, url: res.url, snippet: res.snippet,
          suggested_channel: res.suggested_channel, text: res.text, via: res.via,
          known_source: res.known_source, known_facts: res.known_facts,
        },
        ...prev.filter(h => h.url !== res.url),
      ]);
      setUrlDraft("");
    },
  });

  const genMut = useMutation({
    mutationFn: () => api.researchQueries(clientId),
    onSuccess: (res) => { setDraft(res.queries.join("\n")); setGenerated(true); },
  });

  const searchMut = useMutation({
    mutationFn: () => api.research(clientId, draft.split("\n").map(q => q.trim()).filter(Boolean)),
    onSuccess: (res) => { setHits(res.hits); },
  });

  const queryCount = draft.split("\n").map(q => q.trim()).filter(Boolean).length;

  return (
    <div className="p-5 max-w-[820px] mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Исследование</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Два входа: своя ссылка — сразу в разбор; или подобрать запросы → поправить →
            искать. Дальше одинаково: выбрать факты → импортировать в матрицу.
          </p>
        </div>
        {!generated && (
          <button
            onClick={() => genMut.mutate()}
            disabled={genMut.isPending}
            className="px-4 py-2 bg-ink text-white text-sm rounded hover:bg-black disabled:opacity-50"
          >
            {genMut.isPending ? "Подбираю…" : "Подобрать запросы"}
          </button>
        )}
      </div>

      {/* Своя ссылка — вход, не требующий поиска: аналитик уже знает материал */}
      <div className="bg-white rounded-lg border border-ink-line p-4 space-y-2">
        <h3 className="text-sm font-semibold">Разобрать свою ссылку</h3>
        <p className="text-[11px] text-ink-mute">
          Материал уже нашли сами — статья, интервью, пост. Вставь ссылку: заберём
          текст страницы и разберём его так же, как находку поиска.
          YouTube уводим в свой ингест — там расшифровка и таймкоды.
        </p>
        <div className="flex gap-2">
          <input
            value={urlDraft}
            onChange={e => setUrlDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && urlDraft.trim()) urlMut.mutate(); }}
            placeholder="https://…"
            className="flex-1 text-sm font-mono border border-ink-line rounded px-2.5 py-2"
          />
          <button
            onClick={() => urlMut.mutate()}
            disabled={urlMut.isPending || !urlDraft.trim()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
          >
            {urlMut.isPending ? "Забираем…" : "Разобрать →"}
          </button>
        </div>
        {urlMut.isError && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1.5">
            {urlMut.error instanceof Error ? urlMut.error.message : "Не удалось разобрать ссылку."}
          </div>
        )}
      </div>

      {/* Step 1 → 2: review & edit the generated queries before searching */}
      {generated && (
        <div className="bg-white rounded-lg border border-ink-line p-5 space-y-3">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold">Поисковые запросы <span className="font-normal text-ink-mute">({queryCount})</span></h3>
            <button onClick={() => genMut.mutate()} disabled={genMut.isPending}
              className="text-[11px] text-ink-mute hover:text-ink">{genMut.isPending ? "…" : "сгенерировать заново"}</button>
          </div>
          <p className="text-[11px] text-ink-mute">Один запрос в строке. Поправь, добавь или удали — потом запускай поиск.</p>
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            rows={Math.max(4, draft.split("\n").length + 1)}
            className="w-full text-sm font-mono border border-ink-line rounded px-2.5 py-2 leading-relaxed"
            placeholder='напр. "Имя Фамилия" "Компания" interview'
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => searchMut.mutate()}
              disabled={searchMut.isPending || queryCount === 0}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {searchMut.isPending ? "Ищем…" : `🔍 Искать (${queryCount})`}
            </button>
            <button onClick={() => { setGenerated(false); setDraft(""); setHits([]); }}
              className="text-xs text-ink-mute hover:text-ink">сбросить</button>
          </div>
        </div>
      )}

      {searchMut.isError && (
        <div className="text-sm text-red-600 bg-red-50 rounded p-3">
          Ошибка поиска. Проверь TAVILY_API_KEY на сервере.
        </div>
      )}

      {hits.length === 0 && !searchMut.isPending && searchMut.isSuccess && (
        <div className="text-sm text-ink-mute italic">Ничего не найдено.</div>
      )}

      <div className="space-y-4">
        {hits.map((hit, i) => (
          <SourceCard
            key={hit.url + i}
            hit={hit}
            clientId={clientId}
            onImported={() => setImportedCount(c => c + 1)}
          />
        ))}
      </div>
    </div>
  );
}
