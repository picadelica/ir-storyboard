import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Dossier, DossierLayer } from "../types";

type Health = "green" | "amber" | "thin";
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
