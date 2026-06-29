import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { cellFill, recordAvg } from "../lib/cellFill";
import type { CellSummary, Layer } from "../types";

const cellTotal = (c: CellSummary) => (c.n_green || 0) + (c.n_red || 0) + (c.n_grey || 0);

interface Props {
  clientId: string;
  selectedSubsectionId?: string;
  onSelectCell: (sid: string) => void;
  present?: boolean;
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
  // среднее число записей на непустую ячейку — база для интенсивности заливки
  const avgRecords = recordAvg(cells.data.map(cellTotal));

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
              {/* Layer label — стержень матрицы: крупное имя слоя + номер + покрытие */}
              <div className="w-52 shrink-0 flex items-center gap-3 px-4 py-3 rounded-3xl border border-ink-line bg-white">
                <span className="text-[2.5rem] font-bold leading-none tabular-nums select-none text-ink/25">{L.id}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[15px] font-bold leading-snug text-ink">{L.name}</div>
                  <div className="flex items-center gap-2 mt-2">
                    <div className="h-1.5 flex-1 rounded-full bg-ink/10 overflow-hidden">
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
                  const total = cellTotal(cell);
                  // красный свёрнут в серый: считаем серые = grey + (legacy) red
                  const fill = cellFill(cell.n_green || 0, (cell.n_grey || 0) + (cell.n_red || 0), avgRecords);
                  const selected = selectedSubsectionId === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => onSelectCell(s.id)}
                      title={s.name}
                      style={fill.empty ? undefined : { background: fill.background }}
                      className={`group relative text-left rounded-3xl border px-5 py-4 min-h-[5.25rem] flex items-center transition
                        ${fill.empty ? "bg-white" : ""}
                        ${selected
                          ? "border-blue-500 ring-1 ring-blue-500"
                          : fill.empty
                            ? "border-dashed border-slate-300 hover:border-ink/30"
                            : "border-black/5 hover:border-black/20 hover:shadow-sm"}`}
                    >
                      {/* must-have — деликатно в углу */}
                      {(cell.n_must_client || cell.n_must_expert) ? (
                        <div className="absolute top-3 right-4 flex items-center gap-2 text-[12px] font-semibold leading-none">
                          {cell.n_must_client ? <span className="text-flag-blue" title="must-have от клиента">★{cell.n_must_client}</span> : null}
                          {cell.n_must_expert ? <span className="text-purple-600" title="важное от эксперта">★{cell.n_must_expert}</span> : null}
                        </div>
                      ) : null}

                      <div className="flex-1 flex items-center justify-between gap-3">
                        <span className={`font-bold leading-tight text-[15px] md:text-[17px] ${fill.empty ? "text-ink-mute" : "text-ink"}`}>{s.name}</span>
                        {total > 0
                          ? <span className="shrink-0 text-3xl md:text-4xl font-bold tabular-nums leading-none text-ink/90">{total}</span>
                          : <span className="shrink-0 text-2xl leading-none text-ink-line">+</span>}
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
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-mute">
      <div className="flex items-center gap-1.5">
        {/* шкала интенсивности: меньше записей светлее → больше темнее */}
        <span className="inline-flex h-2.5 w-12 rounded-full overflow-hidden border border-black/5"
          style={{ background: "linear-gradient(to right, hsl(96,45%,88%), hsl(96,45%,58%))" }} />
        <span>меньше / больше записей</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-sm border border-black/5" style={{ background: "hsl(45,10%,85%)" }} />
        <span>серое (пробел)</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-sm border border-dashed border-slate-300" />
        <span>пусто</span>
      </div>
      <span className="w-px h-3 bg-ink-line mx-0.5" />
      <div className="flex items-center gap-1"><span className="text-flag-blue leading-none">★</span> must-have клиента</div>
      <div className="flex items-center gap-1"><span className="text-purple-600 leading-none">★</span> важное эксперта</div>
    </div>
  );
}
