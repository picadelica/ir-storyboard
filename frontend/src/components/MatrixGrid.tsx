import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { modeOf } from "../lib/cellColor";
import type { CellMode } from "../lib/cellColor";
import type { CellSummary, Channel, Layer } from "../types";

interface Props {
  clientId: string;
  selectedSubsectionId?: string;
  onSelectCell: (sid: string) => void;
  present?: boolean;
}

const DOT: Record<CellMode, string> = {
  green: "bg-flag-green",
  red: "bg-flag-red",
  grey: "bg-flag-grey",
  mixed: "bg-flag-mixed",
  empty: "",
};

const CHANNEL_LABEL: Record<Channel, string> = {
  offline_interview: "Offline interview",
  online_interview: "Online interview",
  archival: "Archival",
  online_research: "Web research",
};

/** Tiny inline stroke icon per source channel — no icon-lib dependency. */
function ChannelIcon({ ch }: { ch: Channel }) {
  const p = { width: 13, height: 13, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const title = CHANNEL_LABEL[ch];
  switch (ch) {
    case "offline_interview":
      return <svg {...p}><title>{title}</title><rect x="9" y="2" width="6" height="11" rx="3" /><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4" /></svg>;
    case "online_interview":
      return <svg {...p}><title>{title}</title><circle cx="12" cy="12" r="9" /><path d="M10 8.5l6 3.5-6 3.5z" /></svg>;
    case "archival":
      return <svg {...p}><title>{title}</title><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11h14V8M10 12h4" /></svg>;
    case "online_research":
      return <svg {...p}><title>{title}</title><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z" /></svg>;
  }
}

function relTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}

/** Thin segmented coverage bar; faint track when the cell is empty. */
function CoverageBar({ cell }: { cell: CellSummary }) {
  const g = cell.n_green || 0, r = cell.n_red || 0, gr = cell.n_grey || 0;
  const total = g + r + gr;
  if (total === 0) {
    return <div className="h-1 rounded-full bg-slate-100" />;
  }
  return (
    <div className="flex gap-px h-1 overflow-hidden rounded-full">
      {g > 0 && <span className="bg-flag-green rounded-full" style={{ flexGrow: g }} />}
      {r > 0 && <span className="bg-flag-red rounded-full" style={{ flexGrow: r }} />}
      {gr > 0 && <span className="bg-flag-grey rounded-full" style={{ flexGrow: gr }} />}
    </div>
  );
}

/** Per-layer coverage: fraction of cells that carry any green signal. */
function layerCoverage(cells: (CellSummary | undefined)[]): number {
  const present = cells.filter(Boolean) as CellSummary[];
  if (present.length === 0) return 0;
  const covered = present.filter(c => (c.n_green || 0) > 0).length;
  return Math.round((covered / present.length) * 100);
}

export default function MatrixGrid({ clientId, selectedSubsectionId, onSelectCell, present }: Props) {
  const qc = useQueryClient();
  const layers = useQuery<Layer[]>({ queryKey: ["layers"], queryFn: api.layers });
  const cells = useQuery<CellSummary[]>({
    queryKey: ["matrix", clientId],
    queryFn: () => api.matrixView(clientId),
  });
  const genTitles = useMutation({
    mutationFn: () => api.generateTitles(clientId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["facts", clientId] }); },
  });

  if (layers.isLoading || cells.isLoading) {
    return <div className="p-6 text-sm text-ink-mute">Loading matrix…</div>;
  }
  if (!layers.data || !cells.data) {
    return <div className="p-6 text-sm text-red-600">Failed to load.</div>;
  }

  const cellBySid = new Map(cells.data.map(c => [c.subsection_id, c]));
  const totalMust = cells.data.reduce((n, c) => n + (c.n_must || 0), 0);

  return (
    <div className={`p-5 ${present ? "px-6" : ""}`}>
      <div className="flex items-end justify-between mb-4">
        {present ? <span /> : <h2 className="text-lg font-semibold tracking-tight">Narrative matrix</h2>}
        <div className="flex items-center gap-3">
          {!present && (
            <button
              onClick={() => genTitles.mutate()}
              disabled={genTitles.isPending}
              title="Сгенерировать короткие заголовки (2-3 слова) для карточек без заголовка"
              className="text-xs text-ink-mute border border-ink-line rounded px-2.5 py-1 hover:bg-slate-50 disabled:opacity-50"
            >
              {genTitles.isPending ? "Генерирую заголовки…"
                : genTitles.isSuccess ? `Готово: ${genTitles.data?.titled ?? 0} заголовков`
                : "Заголовки карточек"}
            </button>
          )}
          {!present && totalMust > 0 && (
            <button
              onClick={() => api.downloadMustHaveFacts(clientId, clientId).catch(() => {})}
              title="Скачать must-have факты нумерованным списком для согласования с заказчиком"
              className="flex items-center gap-1.5 text-xs text-flag-blue border border-flag-blue/40 rounded px-2.5 py-1 hover:bg-flag-blue/5"
            >
              <span className="inline-block w-2 h-2 rounded-full bg-flag-blue" />
              Выгрузить must-have (★{totalMust})
            </button>
          )}
          <Legend />
        </div>
      </div>

      <div className="space-y-2">
        {layers.data.map(L => {
          const layerCells = L.subsections.map(s => cellBySid.get(s.id));
          const cov = layerCoverage(layerCells);
          return (
            <div key={L.id} className="flex items-stretch gap-2">
              {/* Layer label: big number + name + mini coverage */}
              <div className="w-44 shrink-0 flex items-center gap-3 px-3.5 py-2.5 rounded-xl border border-ink-line bg-white">
                <span className="text-4xl font-semibold leading-none tabular-nums select-none text-ink/15">{L.id}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium leading-tight text-ink">{L.name}</div>
                  <div className="flex items-center gap-2 mt-2">
                    <div className="h-1 flex-1 rounded-full bg-ink/5 overflow-hidden">
                      <div className="h-full rounded-full bg-flag-green" style={{ width: `${cov}%` }} />
                    </div>
                    <span className="text-[10px] text-ink-mute tabular-nums">{cov}%</span>
                  </div>
                </div>
              </div>

              {/* Cells in this layer */}
              <div
                className="flex-1 grid gap-2"
                style={{ gridTemplateColumns: `repeat(${L.subsections.length}, minmax(0, 1fr))` }}
              >
                {L.subsections.map(s => {
                  const cell = cellBySid.get(s.id);
                  if (!cell) return null;
                  const mode = modeOf(cell);
                  const total = (cell.n_green || 0) + (cell.n_red || 0) + (cell.n_grey || 0);
                  const selected = selectedSubsectionId === s.id;
                  const rel = relTime(cell.last_update);
                  return (
                    <button
                      key={s.id}
                      onClick={() => onSelectCell(s.id)}
                      className={`group text-left rounded-xl border bg-white px-3 py-2.5 transition
                        ${selected
                          ? "border-blue-500 ring-1 ring-blue-500"
                          : "border-ink-line hover:border-ink/30 hover:shadow-sm"}`}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        {mode === "empty" ? (
                          <span className="w-2 h-2 rounded-full border border-dashed border-slate-300 shrink-0" />
                        ) : (
                          <span className={`w-2 h-2 rounded-full shrink-0 ${DOT[mode]}`} />
                        )}
                        <span className="text-[11px] font-mono text-ink-mute tabular-nums">{s.id}</span>
                        <span className="text-[13px] font-medium leading-tight text-ink truncate">{s.name}</span>
                      </div>

                      <CoverageBar cell={cell} />

                      <div className="flex items-center justify-between mt-2.5 text-[11px] text-ink-mute">
                        {total === 0 ? (
                          <span className="inline-flex items-center gap-1 text-ink-mute/70">
                            <span className="text-sm leading-none">+</span> open gap
                          </span>
                        ) : (
                          <span className="tabular-nums">
                            {total} fact{total === 1 ? "" : "s"}
                            {cell.n_red ? <span className="text-flag-red"> · {cell.n_red} concern</span> : null}
                            {cell.n_must ? <span className="text-flag-blue"> · ★{cell.n_must}</span> : null}
                          </span>
                        )}
                        <span className="flex items-center gap-1.5">
                          {(cell.channels ?? []).map(ch => (
                            <span key={ch} className="text-ink-mute/70">
                              <ChannelIcon ch={ch} />
                            </span>
                          ))}
                          {rel && <span className="tabular-nums text-ink-mute/60 ml-0.5">{rel}</span>}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Legend() {
  const items: { mode: CellMode; label: string }[] = [
    { mode: "green", label: "covered" },
    { mode: "red", label: "concern" },
    { mode: "mixed", label: "mixed" },
    { mode: "grey", label: "gap" },
    { mode: "empty", label: "untouched" },
  ];
  return (
    <div className="flex gap-3 text-[11px] text-ink-mute">
      {items.map(({ mode, label }) => (
        <div key={mode} className="flex items-center gap-1.5">
          {mode === "empty" ? (
            <span className="w-2 h-2 rounded-full border border-dashed border-slate-300" />
          ) : (
            <span className={`w-2 h-2 rounded-full ${DOT[mode]}`} />
          )}
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}
