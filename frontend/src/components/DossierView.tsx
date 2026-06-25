import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Dossier, DossierLayer, DossierCell, Fact, Flag } from "../types";
import FlagDot from "./FlagDot";

type Health = "green" | "amber" | "thin";
type DomFlag = "green" | "red" | "grey" | "empty";

const CELLC: Record<DomFlag, { bg: string; fg: string }> = {
  green: { bg: "#EAF3DE", fg: "#3B6D11" },
  red: { bg: "#FCEBEB", fg: "#A32D2D" },
  grey: { bg: "#F1EFE8", fg: "#5F5E5A" },
  empty: { bg: "transparent", fg: "#B4B2A9" },
};
function dominant(c: DossierCell): DomFlag {
  if (c.facts === 0) return "empty";
  const m = Math.max(c.n_green, c.n_red, c.n_grey);
  if (c.n_red === m) return "red";
  if (c.n_green === m) return "green";
  return "grey";
}
function staleDays(ts?: string | null): number {
  if (!ts) return 9999;
  const d = new Date(ts.replace(" ", "T") + (ts.includes("Z") ? "" : "Z"));
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  return isNaN(days) ? 9999 : days;
}
const CHAN: Record<string, string> = {
  offline_interview: "интервью", online_interview: "интервью",
  online_research: "веб", archival: "архив",
};
// подписанный health-pill: цвет + слово (читается сразу, без абстрактных баров)
const PILL: Record<Health, { bg: string; fg: string; label: string }> = {
  green: { bg: "#EAF3DE", fg: "#3B6D11", label: "покрыто" },
  amber: { bg: "#FAEEDA", fg: "#854F0B", label: "частично" },
  thin: { bg: "#F1EFE8", fg: "#5F5E5A", label: "пробел" },
};

function health(l: DossierLayer): Health {
  if (l.facts === 0) return "thin";
  const cov = l.cells_filled / (l.cells_total || 3);
  if (cov >= 0.66 && l.n_green > 0) return "green";
  if (cov < 0.34) return "thin";
  return "amber";
}

function plural(n: number): string {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return "фактов";
  if (b === 1) return "факт";
  if (b >= 2 && b <= 4) return "факта";
  return "фактов";
}

function relTime(ts?: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts.replace(" ", "T") + (ts.includes("Z") ? "" : "Z"));
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (isNaN(days)) return "—";
  if (days <= 0) return "сегодня";
  if (days < 7) return `${days} дн назад`;
  if (days < 60) return `${Math.floor(days / 7)} нед назад`;
  return `${Math.floor(days / 30)} мес назад`;
}

// Карта знаний: 8 строк (слои) × 3 клетки (подсекции). Цвет = доминирующий флаг,
// число = факты, ✓ = корроборация, ★ = must-have, тусклая рамка = устарело.
function KnowledgeMap({ layers, onPick }: { layers: DossierLayer[]; onPick: (sid: string, name: string) => void }) {
  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">Карта знаний</h3>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-mute">
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: CELLC.green.bg }} /> факты</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: CELLC.red.bg }} /> риск</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm border border-dashed border-ink-line" /> пробел</span>
          <span>✓ 2+ источника</span>
          <span>★ must-have</span>
        </div>
      </div>
      <div className="space-y-1.5">
        {layers.map(l => (
          <div key={l.layer_id} className="flex items-center gap-2">
            <div className="w-44 shrink-0 flex items-baseline gap-1.5 min-w-0">
              <span className="text-[11px] text-ink-mute tabular-nums">{l.layer_id}</span>
              <span className="text-[12px] truncate" title={l.name}>{l.name}</span>
            </div>
            <div className="flex gap-1.5">
              {l.cells.map(c => {
                const dom = dominant(c);
                const col = CELLC[dom];
                const stale = c.facts > 0 && staleDays(c.last_update) > 45;
                return (
                  <button key={c.subsection_id} onClick={() => onPick(c.subsection_id, c.subsection_name)}
                    title={`${c.subsection_id} ${c.subsection_name}: ${c.facts} фактов${c.n_red ? `, ${c.n_red} риск` : ""}${c.corroborated ? ", есть 2+ источника" : ""}${c.must_have ? ", must-have" : ""}`}
                    className={`relative w-16 h-11 rounded flex items-center justify-center transition hover:ring-2 hover:ring-ink/20 ${dom === "empty" ? "border border-dashed border-ink-line" : ""} ${stale ? "opacity-60" : ""}`}
                    style={dom === "empty" ? undefined : { background: col.bg }}>
                    <span className="text-[13px] font-semibold tabular-nums" style={{ color: col.fg }}>
                      {c.facts || ""}
                    </span>
                    {c.n_red > 0 && dom !== "red" && <span className="absolute top-1 left-1 w-1.5 h-1.5 rounded-full bg-flag-red" />}
                    {c.must_have && <span className="absolute top-0.5 right-1 text-[10px] leading-none text-flag-blue">★</span>}
                    {c.corroborated && <span className="absolute bottom-0.5 right-1 text-[9px] leading-none" style={{ color: col.fg }}>✓</span>}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// Клик по клетке карты → карточки этой подсекции (все флаги).
function CellCards({ clientId, sid, name, onClose }: { clientId: string; sid: string; name: string; onClose: () => void }) {
  const q = useQuery<Fact[]>({ queryKey: ["cellFacts", clientId, sid], queryFn: () => api.cellFacts(clientId, sid) });
  const facts = (q.data || []).filter(f => f.state !== "rejected");
  return (
    <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10" onClick={onClose}>
      <div className="bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-ink-line">
          <h3 className="text-sm font-semibold">{sid} · {name} <span className="text-ink-mute font-normal">· {facts.length}</span></h3>
          <button onClick={onClose} className="text-ink-mute hover:text-ink text-sm">✕</button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-3 space-y-2">
          {q.isLoading ? <div className="text-sm text-ink-mute px-1 py-2">Загружаю…</div>
            : facts.length === 0 ? <div className="text-sm text-ink-mute px-1 py-2">В ячейке нет карточек — пробел.</div>
            : facts.map(f => (
              <div key={f.id} className="rounded-lg border border-ink-line p-3">
                <div className="flex items-center gap-2 mb-1">
                  <FlagDot flag={f.flag as Flag} size={9} />
                  <span className="text-[11px] font-mono text-ink-mute">#{f.id}</span>
                  {f.must_have && <span className={`text-[12px] leading-none ${f.must_have_by === "expert" ? "text-purple-600" : "text-flag-blue"}`}>★</span>}
                </div>
                {f.title && <div className="text-sm font-semibold text-ink leading-tight mb-0.5">{f.title}</div>}
                <div className="text-sm text-ink leading-snug" style={{ textAlign: "justify" }}>{f.text}</div>
                {f.flag !== "green" && f.rationale && (
                  <div className={`mt-1.5 text-xs border-l-2 pl-2 leading-snug ${f.flag === "red" ? "border-flag-red/60 text-flag-red" : "border-flag-grey/60 text-ink-mute"}`}>{f.rationale}</div>
                )}
                {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="inline-block mt-1.5 text-[11px] text-blue-600 hover:underline">источник ↗</a>}
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-slate-50 rounded-lg px-3 py-2 flex flex-col">
      <div className="text-[11px] text-ink-mute leading-tight min-h-[2.2em]">{label}</div>
      <div className="text-[22px] leading-tight font-semibold mt-auto" style={accent ? { color: accent } : undefined}>{value}</div>
    </div>
  );
}

export default function DossierView({ clientId }: { clientId: string }) {
  const qc = useQueryClient();
  const [pickedCell, setPickedCell] = useState<{ sid: string; name: string } | null>(null);
  const q = useQuery<Dossier>({ queryKey: ["dossier", clientId], queryFn: () => api.dossier(clientId) });
  const gen = useMutation({
    mutationFn: () => api.generateDossier(clientId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dossier", clientId] }),
  });

  if (q.isLoading) return <div className="p-5 text-sm text-ink-mute">Собираю досье…</div>;
  if (q.isError || !q.data) return <div className="p-5 text-sm text-red-600">Не удалось собрать досье.</div>;
  const d = q.data;
  const o = d.overall;

  return (
    <div className="p-5 max-w-4xl space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Досье клиента</h2>
          <p className="text-[13px] text-ink-mute mt-0.5">Целостная картина осведомлённости — без погружения в ячейки.</p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <button onClick={() => gen.mutate()} disabled={gen.isPending}
            title="Пересобрать тексты (exec + синтез по слоям) по текущим фактам"
            className="text-xs text-white bg-ink rounded px-3 py-1.5 hover:bg-black disabled:opacity-50">
            {gen.isPending ? "Собираю тексты…" : d.exec_summary ? "Пересобрать досье" : "Сгенерировать досье"}
          </button>
          {d.generated_at && (
            d.staleness.new_facts > 0
              ? <span className="text-[11px] text-amber-700" title={`собрано ${relTime(d.generated_at)}`}>
                  устарело · +{d.staleness.new_facts} {plural(d.staleness.new_facts)} с тех пор
                </span>
              : <span className="text-[11px] text-ink-mute">актуально · собрано {relTime(d.generated_at)}</span>
          )}
        </div>
      </div>

      {/* hero: метрики (числа — читаемо) + exec */}
      <section className="bg-white rounded-lg border border-ink-line p-4">
        <div className="text-base font-semibold">{d.client.name}</div>
        {(d.client.sector || d.client.one_liner) && (
          <div className="text-[13px] text-ink-mute mb-3">{[d.client.sector, d.client.one_liner].filter(Boolean).join(" · ")}</div>
        )}
        <div className="grid grid-cols-4 gap-2.5">
          <Metric label="Фактов" value={String(o.facts)} />
          <Metric label="Покрытие" value={`${o.coverage_pct}%`} />
          <Metric label="2+ источника" value={`${o.corroborated_pct}%`} />
          <Metric label="Риски" value={String(o.red)} accent={o.red ? "#A32D2D" : undefined} />
        </div>
        <div className="mt-4 pt-3 border-t border-ink-line/60">
          {d.exec_summary
            ? <p className="text-sm leading-relaxed text-ink" style={{ textAlign: "justify" }}>{d.exec_summary}</p>
            : <p className="text-[13px] text-ink-mute italic">Тексты ещё не сгенерированы — нажми «Сгенерировать досье»: соберём exec-summary и синтез по слоям из фактов.</p>}
        </div>
      </section>

      {/* карта знаний: тепловая решётка 8×3 — реальные ячейки, пробелы видны дырками */}
      <KnowledgeMap layers={d.layers} onPick={(sid, name) => setPickedCell({ sid, name })} />

      {pickedCell && (
        <CellCards clientId={clientId} sid={pickedCell.sid} name={pickedCell.name} onClose={() => setPickedCell(null)} />
      )}

      {/* слои: подписанный health-pill (скан сверху вниз) + синтез + чистая строка */}
      <div className="space-y-2">
        {d.layers.map(l => {
          const p = PILL[health(l)];
          return (
            <div key={l.layer_id} className="bg-white rounded-lg border border-ink-line p-3.5">
              <div className="flex items-center justify-between gap-3 mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0" style={{ background: p.bg, color: p.fg }}>{p.label}</span>
                  <span className="text-[11px] text-ink-mute tabular-nums shrink-0">{l.layer_id}</span>
                  <span className="text-sm font-medium truncate">{l.name}</span>
                </div>
                <div className="flex items-center gap-2.5 text-[12px] shrink-0">
                  <span className="text-ink-mute">{l.facts} {plural(l.facts)}</span>
                  {l.n_red > 0 && <span className="text-flag-red">{l.n_red} риск</span>}
                  {l.n_must_client > 0 && <span className="text-flag-blue" title="must-have клиента">★{l.n_must_client}</span>}
                  {l.n_must_expert > 0 && <span className="text-purple-600" title="важное эксперта">★{l.n_must_expert}</span>}
                </div>
              </div>
              <div className="text-[13px] text-ink-mute leading-snug mb-2" style={{ textAlign: "justify" }}>
                {l.summary || <span className="italic">синтез появится после генерации досье</span>}
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-mute/90">
                <span>{l.cells_filled}/{l.cells_total} раздела</span>
                {l.corroborated > 0 && <span>подтв. {l.corroborated}</span>}
                {l.channels.length > 0 && <span>{[...new Set(l.channels.map(c => CHAN[c] || c))].join(", ")}</span>}
                <span>обновлено {relTime(l.last_update)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
