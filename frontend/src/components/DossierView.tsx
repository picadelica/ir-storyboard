import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Dossier, DossierLayer } from "../types";

const HEX = { green: "#639922", amber: "#BA7517", thin: "#B4B2A9" };
const CHAN: Record<string, string> = {
  offline_interview: "интервью", online_interview: "интервью",
  online_research: "веб", archival: "архив",
};

function health(l: DossierLayer): "green" | "amber" | "thin" {
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
  if (days < 7) return `${days} дн`;
  if (days < 60) return `${Math.floor(days / 7)} нед`;
  return `${Math.floor(days / 30)} мес`;
}

function Rings({ layers }: { layers: DossierLayer[] }) {
  const cx = 100, cy = 100;
  return (
    <svg viewBox="0 0 200 200" width="172" height="172" role="img" aria-label="Кольца осведомлённости по слоям">
      {layers.map((l, i) => {
        const r = 16 + i * 9;
        const c = 2 * Math.PI * r;
        const frac = Math.max(0.06, Math.min(1, l.cells_filled / (l.cells_total || 3)));
        return (
          <g key={l.layer_id}>
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--ring-bg, #E6E4DC)" strokeWidth={6} />
            <circle cx={cx} cy={cy} r={r} fill="none" stroke={HEX[health(l)]} strokeWidth={6}
              strokeLinecap="round" strokeDasharray={`${frac * c} ${c}`}
              transform={`rotate(-90 ${cx} ${cy})`} />
          </g>
        );
      })}
    </svg>
  );
}

function FactsBar({ l }: { l: DossierLayer }) {
  const tot = l.facts || 1;
  const seg = (v: number, color: string) =>
    v ? <span style={{ width: `${(v / tot) * 56}px`, background: color }} className="rounded-sm" /> : null;
  return (
    <span className="inline-flex gap-px h-1.5 w-14 align-middle">
      {seg(l.n_green, HEX.green)}{seg(l.n_red, "#E24B4A")}{seg(l.n_grey, HEX.thin)}
    </span>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-slate-50 rounded-lg px-3 py-2">
      <div className="text-[11px] text-ink-mute">{label}</div>
      <div className="text-[22px] leading-tight font-semibold" style={accent ? { color: accent } : undefined}>{value}</div>
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
    <div className="p-5 max-w-5xl space-y-4">
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
              ? <span className="text-[11px] text-amber-700" title={`собрано ${relTime(d.generated_at)} назад`}>
                  устарело · +{d.staleness.new_facts} {plural(d.staleness.new_facts)} с тех пор
                </span>
              : <span className="text-[11px] text-ink-mute">актуально · собрано {relTime(d.generated_at)} назад</span>
          )}
        </div>
      </div>

      {/* hero: кольца + метрики + exec */}
      <section className="bg-white rounded-lg border border-ink-line p-4">
        <div className="flex gap-5 items-start flex-wrap">
          <Rings layers={d.layers} />
          <div className="flex-1 min-w-[260px]">
            <div className="text-base font-semibold">{d.client.name}</div>
            {(d.client.sector || d.client.one_liner) && (
              <div className="text-[13px] text-ink-mute mb-2.5">
                {[d.client.sector, d.client.one_liner].filter(Boolean).join(" · ")}
              </div>
            )}
            <div className="grid grid-cols-4 gap-2.5">
              <Metric label="Фактов" value={String(o.facts)} />
              <Metric label="Покрытие" value={`${o.coverage_pct}%`} />
              <Metric label="Подтв." value={`${o.corroborated_pct}%`} />
              <Metric label="Риски" value={String(o.red)} accent={o.red ? "#A32D2D" : undefined} />
            </div>
          </div>
        </div>
        <div className="mt-4 pt-3 border-t border-ink-line/60">
          {d.exec_summary
            ? <p className="text-sm leading-relaxed text-ink" style={{ textAlign: "justify" }}>{d.exec_summary}</p>
            : <p className="text-[13px] text-ink-mute italic">Тексты ещё не сгенерированы — нажми «Сгенерировать досье»: соберём exec-summary и синтез по слоям из фактов.</p>}
        </div>
      </section>

      {/* слои */}
      <div className="space-y-2">
        {d.layers.map(l => {
          const h = health(l);
          return (
            <div key={l.layer_id} className="bg-white rounded-lg border border-ink-line p-3.5">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-[7px] h-[7px] rounded-full shrink-0" style={{ background: HEX[h] }} />
                <span className="text-[11px] text-ink-mute tabular-nums">{l.layer_id}</span>
                <span className="text-sm font-medium">{l.name}</span>
              </div>
              <div className="text-[13px] text-ink-mute leading-snug mb-2" style={{ textAlign: "justify" }}>
                {l.summary || <span className="italic">синтез появится после генерации досье</span>}
              </div>
              <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[12px] text-ink-mute">
                <span className="inline-flex items-center gap-1.5"><FactsBar l={l} />{l.facts} фактов</span>
                <span>{l.cells_filled}/{l.cells_total} ячеек</span>
                {l.channels.length > 0 && (
                  <span>{[...new Set(l.channels.map(c => CHAN[c] || c))].join(" · ")}</span>
                )}
                {l.corroborated > 0 && <span>подтв. {l.corroborated}</span>}
                <span>{relTime(l.last_update)}</span>
                <span className="inline-flex items-center gap-2 ml-auto">
                  {l.n_red > 0 && <span className="text-flag-red">{l.n_red} риск</span>}
                  {l.n_must_client > 0 && <span className="text-flag-blue">★{l.n_must_client}</span>}
                  {l.n_must_expert > 0 && <span className="text-purple-600">★{l.n_must_expert}</span>}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
