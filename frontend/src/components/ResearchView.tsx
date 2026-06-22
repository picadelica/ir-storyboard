import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { FactCandidateOut, Flag, IngestPreviewOut, SearchHit } from "../types";

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
  return (
    <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${CHANNEL_COLORS[ch] ?? "bg-slate-100"}`}>
      {ch.replace("_", " ")}
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
            title="Subsection ID"
          />
          <span className="text-[10px] text-ink-mute truncate">
            {cand.suggested_layer_name} → {cand.suggested_subsection_name}
          </span>
          {/* flag picker */}
          <select
            value={flag}
            onChange={e => onFlag(e.target.value as Flag)}
            className={`text-[10px] border rounded px-1 py-0.5 ${FLAG_COLORS[flag]}`}
          >
            <option value="green">green</option>
            <option value="red">red</option>
            <option value="grey">grey</option>
          </select>
          {cand.confidence < 0.6 && (
            <span className="text-[9px] text-amber-600">conf {(cand.confidence * 100).toFixed(0)}%</span>
          )}
        </div>
        {cand.rationale && (
          <div className="text-[10px] text-ink-mute italic">{cand.rationale}</div>
        )}
        {flag === "red" && (
          <input
            value={rationale}
            onChange={e => onRationale(e.target.value)}
            placeholder="Concern: что именно проблема (обязательно для red)"
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
  hit: SearchHit;
  clientId: string;
  onImported: () => void;
}

function SourceCard({ hit, clientId, onImported }: SourceCardProps) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [preview, setPreview] = useState<IngestPreviewOut | null>(null);
  const [customText, setCustomText] = useState("");
  const [showPaste, setShowPaste] = useState(false);
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
        throw new Error("Нет текста для классификации. Открой 'Paste full text' и вставь текст статьи.");
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
      alert(`Classify failed: ${msg}`);
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
      </div>

      {/* YouTube redirect banner */}
      {youtubeUrl ? (
        <div className="mx-3 mb-3 border border-pink-300 bg-pink-50 rounded p-3 space-y-2">
          <div className="flex items-start gap-2">
            <span className="text-pink-600 text-base shrink-0">🎥</span>
            <div className="text-xs text-pink-900 leading-snug flex-1">
              {directYouTubeUrl ? (
                <>Это YouTube-ссылка — текстовая классификация даст плохой результат.
                  Лучше обработать через <b>YouTube Ingest</b>: будет полный транскрипт
                  с таймкодами, факты с цитатами.</>
              ) : (
                <>В этом твите/посте есть ссылка на YouTube
                  (<code className="bg-pink-100 px-1 rounded">{youtubeUrl}</code>).
                  Рекомендуем обработать видео через <b>YouTube Ingest</b>.</>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={processViaYouTube}
            className="w-full text-xs px-3 py-1.5 bg-pink-600 text-white rounded hover:bg-pink-700"
          >
            Process via YouTube ingest →
          </button>
        </div>
      ) : (
        <div className="px-3 pb-3 flex items-center gap-2 flex-wrap">
          <select
            value={channel}
            onChange={e => setChannel(e.target.value as Channel)}
            className="text-xs border border-ink-line rounded px-1.5 py-1"
          >
            <option value="online_research">online_research</option>
            <option value="online_interview">online_interview</option>
            <option value="archival">archival</option>
          </select>
          <button
            onClick={() => setShowPaste(p => !p)}
            className="text-xs px-2 py-1 border border-ink-line rounded hover:bg-slate-50 text-ink-mute"
          >{showPaste ? "Hide paste" : "Paste full text"}</button>
          <button
            type="button"
            onClick={() => classifyMut.mutate()}
            disabled={classifyMut.isPending}
            className="text-xs px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 ml-auto cursor-pointer"
          >{classifyMut.isPending ? "Extracting…" : "Extract facts →"}</button>
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
              Classified facts — {preview.candidates.length} found
            </span>
            <button
              onClick={() => setRows(r => r.map(x => ({ ...x, checked: true })))}
              className="text-[10px] text-blue-600 hover:underline"
            >Select all</button>
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
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [draft, setDraft] = useState("");          // editable queries, one per line
  const [generated, setGenerated] = useState(false);
  const [, setImportedCount] = useState(0);

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
    <div className="p-5 space-y-5 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Research</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Подобрать запросы → проверить и поправить → искать → выбрать факты → импортировать в матрицу
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

      {/* Step 1 → 2: review & edit the generated queries before searching */}
      {generated && (
        <div className="bg-white rounded-lg border border-ink-line p-4 space-y-2">
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
