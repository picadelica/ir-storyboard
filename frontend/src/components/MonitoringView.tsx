import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDuration } from "./IngestYouTube";
import type { Entity, MonitorCandidate, WatchlistItem, WatchlistKind, WatchlistSuggestion } from "../types";

interface Props {
  clientId: string;
}

const RELEVANCE_STYLE: Record<string, { label: string; cls: string }> = {
  likely: { label: "похоже, наш", cls: "bg-flag-green-bg text-flag-green border-flag-green/40" },
  unclear: { label: "не разобрать", cls: "bg-flag-mixed-bg text-flag-mixed border-flag-mixed/40" },
  unlikely: { label: "вряд ли наш", cls: "bg-flag-grey-bg text-ink-mute border-ink-line" },
};

const KIND_LABEL: Record<WatchlistKind, string> = {
  youtube_channel: "канал",
  rss: "фид",
  search_query: "поиск",
};

/** Русские числительные: 1 находка, 2 находки, 5 находок. */
function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** Мониторинг: что смотрим за клиентом и что нашлось. Разбор — обычный ингест. */
export default function MonitoringView({ clientId }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [error, setError] = useState("");
  const [showSources, setShowSources] = useState(false);
  const [showFiltered, setShowFiltered] = useState(false);

  const candidates = useQuery<MonitorCandidate[]>({
    queryKey: ["monitor-candidates", clientId],
    queryFn: () => api.monitorCandidates(clientId),
  });
  const items = useQuery<WatchlistItem[]>({
    queryKey: ["watchlist", clientId],
    queryFn: () => api.watchlist(clientId),
  });
  const suggestions = useQuery<WatchlistSuggestion[]>({
    queryKey: ["watchlist-suggestions", clientId],
    queryFn: () => api.watchlistSuggestions(clientId),
  });
  const entities = useQuery<Entity[]>({
    queryKey: ["entities", clientId],
    queryFn: () => api.entities(clientId),
  });
  const founders = (entities.data ?? []).filter(e => e.kind === "founder");

  function refresh() {
    qc.invalidateQueries({ queryKey: ["monitor-candidates", clientId] });
    qc.invalidateQueries({ queryKey: ["watchlist", clientId] });
    qc.invalidateQueries({ queryKey: ["watchlist-suggestions", clientId] });
  }

  const checkMut = useMutation({
    mutationFn: (body: { client_id?: string; item_id?: number }) => api.checkMonitoring(body),
    onSuccess: () => { setError(""); refresh(); },
    onError: (e: Error) => setError(e.message),
  });
  const dismissMut = useMutation({
    mutationFn: (id: number) => api.dismissCandidate(id),
    onSuccess: refresh,
    onError: (e: Error) => setError(e.message),
  });
  const ingestMut = useMutation({
    mutationFn: (id: number) => api.startCandidateIngest(id),
    onSuccess: (res) => {
      refresh();
      // Разбор — существующий экран ингеста с предзаполненной ссылкой.
      nav(`/clients/${clientId}/youtube?url=${encodeURIComponent(res.url)}`);
    },
    onError: (e: Error) => setError(e.message),
  });

  const list = candidates.data ?? [];
  // Отсеянное фильтром не мешается в очереди, но и не пропадает: аналитик должен
  // иметь возможность проверить, что фильтр не выбросил лишнего.
  const queue = list.filter(c => c.relevance !== "unlikely");
  const filteredOut = list.filter(c => c.relevance === "unlikely");
  const activeCount = (items.data ?? []).filter(i => i.status === "active").length;

  return (
    <div className="p-5 space-y-6 max-w-5xl">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Мониторинг</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Система сама следит за каналами и подкастами спикеров и приносит новые
            выступления. Разбирает — по-прежнему аналитик, обычным ингестом.
          </p>
        </div>
        <button
          onClick={() => checkMut.mutate({ client_id: clientId })}
          disabled={checkMut.isPending || activeCount === 0}
          className="text-xs px-3 py-1.5 rounded border border-ink-line hover:bg-slate-100 disabled:opacity-40 whitespace-nowrap"
        >
          {checkMut.isPending ? "проверяем…" : "Проверить сейчас"}
        </button>
      </div>

      {error && (
        <div className="text-xs text-flag-red bg-flag-red-bg border border-flag-red/30 rounded p-2">
          {error}
        </div>
      )}
      {checkMut.data && !checkMut.isPending && (
        <div className="text-xs text-ink-mute">
          Проверено источников: {checkMut.data.items_checked ?? 1} · просмотрено {checkMut.data.found} ·
          новых для нас {checkMut.data.new} (сколько из них дошло до очереди — ниже)
          {(checkMut.data.errors ?? []).length > 0 && (
            <span className="text-flag-red"> · с ошибкой: {(checkMut.data.errors ?? []).length}</span>
          )}
        </div>
      )}

      {/* ── очередь находок ── */}
      <section className="space-y-3">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-medium">Новые выступления</h3>
          <span className="text-xs text-ink-mute">{queue.length}</span>
        </div>

        {candidates.isLoading && <div className="text-sm text-ink-mute">Загружаем…</div>}
        {!candidates.isLoading && queue.length === 0 && (
          <div className="text-sm text-ink-mute border border-dashed border-ink-line rounded p-4">
            {activeCount === 0
              ? "Пока не за чем следить — добавьте канал, фид или поиск по имени спикера ниже."
              : filteredOut.length > 0
                ? `Новых выступлений нет: ${filteredOut.length} ${plural(filteredOut.length,
                    "находка отсеяна", "находки отсеяны", "находок отсеяно")} как чужие.`
                : "Новых выступлений нет. Как появятся — окажутся здесь."}
          </div>
        )}

        <ul className="space-y-2">
          {queue.map(c => {
            const rel = RELEVANCE_STYLE[c.relevance] ?? RELEVANCE_STYLE.unclear;
            return (
              <li key={c.id} className="border border-ink-line rounded p-3 flex gap-3">
                {c.thumb_url ? (
                  <img src={c.thumb_url} alt="" className="w-28 h-16 object-cover rounded shrink-0" />
                ) : (
                  <div className="w-28 h-16 rounded bg-flag-empty-bg shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-2">
                    <a href={c.url} target="_blank" rel="noreferrer"
                       className="text-sm font-medium hover:underline break-words">
                      {c.title || c.norm_url}
                    </a>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${rel.cls}`}>
                      {rel.label}
                    </span>
                  </div>
                  <div className="text-xs text-ink-mute mt-1">
                    {[c.published_at, c.duration_sec ? fmtDuration(c.duration_sec) : "", c.item_label]
                      .filter(Boolean).join(" · ")}
                  </div>
                  {c.relevance_note && (
                    <div className="text-xs text-ink-mute mt-1 italic">{c.relevance_note}</div>
                  )}
                </div>
                <div className="flex flex-col gap-1.5 shrink-0">
                  <button
                    onClick={() => ingestMut.mutate(c.id)}
                    disabled={ingestMut.isPending}
                    className="text-xs px-3 py-1.5 rounded bg-ink text-white hover:opacity-90 disabled:opacity-40"
                  >
                    Разобрать
                  </button>
                  <button
                    onClick={() => dismissMut.mutate(c.id)}
                    disabled={dismissMut.isPending}
                    className="text-xs px-3 py-1.5 rounded border border-ink-line hover:bg-slate-100"
                  >
                    Скрыть
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        {/* Отсеянное — свёрнуто. Не прячем совсем: если фильтр ошибётся, аналитик
            должен это увидеть и вытащить находку руками. */}
        {filteredOut.length > 0 && (
          <div>
            <button onClick={() => setShowFiltered(v => !v)}
                    className="text-xs text-ink-mute hover:text-ink">
              {showFiltered ? "▾" : "▸"} Отсеяно как чужое ({filteredOut.length})
            </button>
            {showFiltered && (
              <ul className="mt-2 space-y-1.5">
                {filteredOut.map(c => (
                  <li key={c.id} className="text-xs flex items-baseline gap-2 border-l-2 border-ink-line pl-3">
                    <a href={c.url} target="_blank" rel="noreferrer"
                       className="text-ink-mute hover:text-ink hover:underline break-words">
                      {c.title || c.norm_url}
                    </a>
                    <span className="text-ink-mute shrink-0">·</span>
                    <span className="text-ink-mute italic min-w-0 flex-1">{c.relevance_note}</span>
                    <button onClick={() => ingestMut.mutate(c.id)}
                            className="text-blue-600 hover:underline shrink-0">всё-таки разобрать</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      {/* ── предложения из уже разобранного ── */}
      {(suggestions.data ?? []).length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium">Предложения</h3>
          <ul className="space-y-2">
            {(suggestions.data ?? []).map(s => (
              <SuggestionRow key={s.channel_name} s={s} clientId={clientId}
                             onDone={refresh} onError={setError} />
            ))}
          </ul>
        </section>
      )}

      {/* ── источники ── */}
      <section className="space-y-3">
        <button onClick={() => setShowSources(v => !v)}
                className="text-sm font-medium hover:underline">
          {showSources ? "▾" : "▸"} За чем следим ({items.data?.length ?? 0})
        </button>

        {showSources && (
          <>
            <ul className="space-y-2">
              {(items.data ?? []).map(it => (
                <li key={it.id} className="border border-ink-line rounded p-3 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm break-words">
                      <span className="text-[10px] font-mono uppercase text-ink-mute mr-2">
                        {KIND_LABEL[it.kind]}
                      </span>
                      {it.label}
                    </div>
                    <div className="text-xs text-ink-mute mt-1">
                      {it.speaker_name ? `спикер: ${it.speaker_name} · ` : ""}
                      {it.last_checked_at
                        ? `проверен ${new Date(it.last_checked_at).toLocaleString()}`
                        : "ещё не проверялся"}
                      {it.status === "paused" && " · на паузе"}
                    </div>
                    {it.last_error && (
                      <div className="text-xs text-flag-red mt-1">не удалось: {it.last_error}</div>
                    )}
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      onClick={() => checkMut.mutate({ item_id: it.id })}
                      disabled={checkMut.isPending}
                      className="text-xs px-2 py-1 rounded border border-ink-line hover:bg-slate-100"
                    >проверить</button>
                    <button
                      onClick={() => api.pauseWatchlistItem(it.id, it.status === "active")
                        .then(refresh).catch((e: Error) => setError(e.message))}
                      className="text-xs px-2 py-1 rounded border border-ink-line hover:bg-slate-100"
                    >{it.status === "active" ? "пауза" : "включить"}</button>
                    <button
                      onClick={() => api.deleteWatchlistItem(it.id)
                        .then(refresh).catch((e: Error) => setError(e.message))}
                      className="text-xs px-2 py-1 rounded border border-ink-line hover:bg-slate-100 text-flag-red"
                    >убрать</button>
                  </div>
                </li>
              ))}
            </ul>
            <AddSourceForm clientId={clientId} founders={founders}
                           onDone={refresh} onError={setError} />
          </>
        )}
      </section>
    </div>
  );
}

function SuggestionRow({ s, clientId, onDone, onError }: {
  s: WatchlistSuggestion; clientId: string; onDone: () => void; onError: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <li className="border border-ink-line rounded p-3 flex items-center justify-between gap-3">
      <div className="text-sm">
        Вы {s.count === 1 ? "уже брали" : `брали ${s.count} видео`} с канала{" "}
        <span className="font-medium">{s.channel_name}</span> — добавить в мониторинг?
      </div>
      <button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          api.addWatchlistItem({
            client_id: clientId, kind: "youtube_channel",
            config: { url: s.sample_url }, label: s.channel_name,
          }).then(onDone).catch((e: Error) => onError(e.message)).finally(() => setBusy(false));
        }}
        className="text-xs px-3 py-1.5 rounded border border-ink-line hover:bg-slate-100 shrink-0"
      >{busy ? "добавляем…" : "Добавить"}</button>
    </li>
  );
}

function AddSourceForm({ clientId, founders, onDone, onError }: {
  clientId: string; founders: Entity[]; onDone: () => void; onError: (m: string) => void;
}) {
  const [kind, setKind] = useState<WatchlistKind>("youtube_channel");
  const [value, setValue] = useState("");
  const [speaker, setSpeaker] = useState<number | "">("");
  const [busy, setBusy] = useState(false);

  const placeholder = kind === "youtube_channel"
    ? "ссылка на канал или на любое видео с него"
    : kind === "rss" ? "ссылка на RSS-фид подкаста"
    : "имя спикера или запрос для поиска";

  function submit() {
    if (!value.trim()) return;
    const config: Record<string, string> =
      kind === "youtube_channel" ? { url: value.trim() }
      : kind === "rss" ? { feed_url: value.trim() }
      : { query: value.trim() };
    setBusy(true);
    api.addWatchlistItem({
      client_id: clientId, kind, config,
      speaker_entity_id: speaker === "" ? null : Number(speaker),
    })
      .then(() => { setValue(""); onDone(); })
      .catch((e: Error) => onError(e.message))
      .finally(() => setBusy(false));
  }

  return (
    <div className="border border-dashed border-ink-line rounded p-3 space-y-2">
      <div className="flex gap-2 flex-wrap">
        {(Object.keys(KIND_LABEL) as WatchlistKind[]).map(k => (
          <button key={k} onClick={() => setKind(k)}
            className={`text-xs px-2.5 py-1 rounded border ${
              kind === k ? "bg-ink text-white border-ink" : "border-ink-line hover:bg-slate-100"}`}>
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>
      <div className="flex gap-2 flex-wrap">
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") submit(); }}
          placeholder={placeholder}
          className="flex-1 min-w-[16rem] text-sm px-2 py-1.5 border border-ink-line rounded"
        />
        {founders.length > 0 && (
          <select value={speaker} onChange={e => setSpeaker(e.target.value === "" ? "" : Number(e.target.value))}
                  className="text-sm px-2 py-1.5 border border-ink-line rounded">
            <option value="">чей источник (необяз.)</option>
            {founders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        )}
        <button onClick={submit} disabled={busy || !value.trim()}
                className="text-xs px-3 py-1.5 rounded bg-ink text-white hover:opacity-90 disabled:opacity-40">
          {busy ? "добавляем…" : "Добавить"}
        </button>
      </div>
    </div>
  );
}
