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
  // агрегат по слою (сумма трёх подсекций) — для заливки колонки названий той же логикой
  const layerAgg = new Map(layers.data.map(L => {
    let g = 0, gr = 0;
    for (const s of L.subsections) { const c = cellBySid.get(s.id); if (c) { g += c.n_green || 0; gr += (c.n_grey || 0) + (c.n_red || 0); } }
    return [L.id, { g, gr, total: g + gr }];
  }));
  const avgLayer = recordAvg([...layerAgg.values()].map(a => a.total));

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
          const la = layerAgg.get(L.id)!;
          const lfill = cellFill(la.g, la.gr, avgLayer);   // заливка по сумме слоя, та же логика
          return (
            <div
              key={L.id}
              className="grid gap-2 items-stretch"
              style={{ gridTemplateColumns: `repeat(${L.subsections.length + 1}, minmax(0, 1fr))` }}
            >
              {/* Колонка названий секций — та же ширина и заливка (по сумме слоя), без процентов */}
              <div
                title={L.name}
                style={lfill.empty ? undefined : { background: lfill.background }}
                className={`relative rounded-3xl border px-5 py-4 min-h-[5.25rem] flex items-center gap-3
                  ${lfill.empty ? "bg-white border-dashed border-slate-300" : "border-black/10"}`}
              >
                <span className="text-2xl font-bold leading-none tabular-nums select-none text-ink/30">{L.id}</span>
                <span className="font-bold leading-tight text-[15px] md:text-[17px] text-ink">{L.name}</span>
              </div>

              {/* Cells in this layer */}
              <>
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
              </>
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
