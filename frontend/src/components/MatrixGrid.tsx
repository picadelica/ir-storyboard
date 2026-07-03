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
            {/* Колонка названий слоёв — белая, типографская: номер серифом + название капителью */}
            <div
              title={L.name}
              className="relative rounded-2xl border border-ink/20 bg-white px-5 py-4 min-h-[5.75rem] flex flex-col justify-between"
            >
              <span className="font-display text-3xl leading-none select-none text-ink/20">{L.id}</span>
              <span className="font-semibold leading-snug text-[11px] uppercase tracking-[0.08em] text-ink/80">{L.name}</span>
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
                    className={`group relative text-left rounded-2xl border px-5 py-4 min-h-[5.75rem] flex flex-col justify-between transition
                      ${fill.empty ? "bg-white/50 border-dashed border-ink/25" : hasMust ? "border-flag-blue" : "border-ink/20"}
                      ${selected ? "ring-2 ring-flag-blue" : "hover:shadow-md hover:-translate-y-px"}`}
                  >
                    {/* верх: название мелким лейблом + must-have в углу */}
                    <div className="flex items-start justify-between gap-2">
                      <span
                        className="font-medium leading-snug text-[12px] tracking-[0.01em]"
                        style={{ color: fill.labelFg }}
                      >{s.name}</span>
                      {hasMust ? (
                        <span className="flex items-center gap-1.5 text-[11px] font-semibold leading-none rounded-full bg-white/80 px-1.5 py-0.5 shrink-0">
                          {cell.n_must_client ? <span className="text-flag-blue" title="must-have от клиента">★{cell.n_must_client}</span> : null}
                          {cell.n_must_expert ? <span className="text-purple-600" title="важное от эксперта">★{cell.n_must_expert}</span> : null}
                        </span>
                      ) : null}
                    </div>

                    {/* низ: крупная цифра серифом, прижата вправо */}
                    <div className="flex justify-end">
                      {total > 0
                        ? <span className="font-display text-[2.4rem] md:text-[2.75rem] leading-[0.9] select-none" style={{ color: fill.fg }}>{total}</span>
                        : <span className="text-2xl leading-none text-ink/20">+</span>}
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
