import { useQuery } from "@tanstack/react-query";
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
  const layers = useQuery<Layer[]>({ queryKey: ["layers"], queryFn: api.layers });
  const cells = useQuery<CellSummary[]>({
    queryKey: ["matrix", clientId],
    queryFn: () => api.matrixView(clientId),
  });

  if (layers.isLoading || cells.isLoading) {
    return <div className="p-6 text-sm text-ink-mute">Loading matrix…</div>;
  }
  if (!layers.data || !cells.data) {
    return <div className="p-6 text-sm text-red-600">Failed to load.</div>;
  }

  const cellBySid = new Map(cells.data.map(c => [c.subsection_id, c]));
  // среднее число записей на непустую ячейку — база для интенсивности заливки
  const avgRecords = recordAvg(cells.data.map(cellTotal));

  return (
    <div className={`p-5 ${present ? "px-6" : ""}`}>
      <div className="space-y-2">
        {layers.data.map(L => (
          <div
            key={L.id}
            className="grid gap-2 items-stretch"
            style={{ gridTemplateColumns: `repeat(${L.subsections.length + 1}, minmax(0, 1fr))` }}
          >
            {/* Колонка названий секций — простой белый фон, тонкая чёрная рамка (не сливается с матрицей) */}
            <div
              title={L.name}
              className="relative rounded-3xl border border-ink bg-white px-5 py-4 min-h-[5.25rem] flex items-center gap-3"
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
                const hasMust = !!(cell.n_must_client || cell.n_must_expert);
                return (
                  <button
                    key={s.id}
                    onClick={() => onSelectCell(s.id)}
                    title={s.name}
                    style={fill.empty ? undefined : { background: fill.background }}
                    className={`group relative text-left rounded-3xl border px-5 py-4 min-h-[5.25rem] flex items-center transition
                      ${fill.empty ? "bg-white" : ""}
                      ${hasMust ? "border-flag-blue" : "border-ink"}
                      ${selected ? "ring-2 ring-flag-blue" : "hover:shadow-sm"}`}
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
        ))}
      </div>
    </div>
  );
}
