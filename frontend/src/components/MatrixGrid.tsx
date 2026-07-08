import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { cellFill, recordAvg } from "../lib/cellFill";
import type { CellSummary, Layer, ReviewFact } from "../types";

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

  // очередь черновиков (state='review') — делает механизм «черновик → одобрение»
  // видимым: контрибьютор добавил факт → он тут; владелец одобряет или открывает ячейку.
  const qc = useQueryClient();
  const review = useQuery<ReviewFact[]>({
    queryKey: ["review-queue", clientId],
    queryFn: () => api.reviewQueue(clientId),
    enabled: !present,
  });
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const canApprove = !me.data?.auth || !!me.data?.is_admin
    || (client.data?.owner_tid != null && me.data?.tid === client.data.owner_tid);
  const [queueOpen, setQueueOpen] = useState(false);
  const approve = useMutation({
    mutationFn: (id: number) => api.promoteFact(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review-queue", clientId] });
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["facts", clientId] });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    },
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

  const queue = review.data ?? [];

  return (
    <div className={`p-5 ${present ? "px-6" : ""}`}>
      {/* полоса очереди одобрения: черновики контрибьюторов вне матрицы, пока владелец не одобрит */}
      {!present && queue.length > 0 && (
        <div className="mb-3 border border-amber-300 bg-amber-50 rounded-xl">
          <button onClick={() => setQueueOpen(o => !o)}
            className="w-full flex items-center gap-2 px-4 py-2.5 text-left">
            <span className="text-[13px] font-medium text-amber-900">
              ⏳ Черновики ждут одобрения владельца: {queue.length}
            </span>
            <span className="text-[11px] text-amber-700/80 hidden sm:inline">
              — в матрице не считаются, пока не одобрены</span>
            <span className="ml-auto text-amber-700">{queueOpen ? "▴" : "▾"}</span>
          </button>
          {queueOpen && (
            <ul className="border-t border-amber-200 divide-y divide-amber-100">
              {queue.map(f => (
                <li key={f.id} className="flex items-start gap-3 px-4 py-2">
                  <span className="shrink-0 font-mono text-[11px] text-amber-700 pt-0.5">{f.subsection_id}</span>
                  <span className="flex-1 text-[13px] text-ink leading-snug">{f.text}</span>
                  <div className="shrink-0 flex items-center gap-2">
                    {canApprove && (
                      <button onClick={() => approve.mutate(f.id)} disabled={approve.isPending}
                        className="text-[11px] px-2 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300">
                        одобрить</button>
                    )}
                    <button onClick={() => onSelectCell(f.subsection_id)}
                      className="text-[11px] text-blue-700 hover:underline">ячейка →</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
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
                    className={`group relative text-left rounded-2xl border px-5 py-4 pb-5 min-h-[5.75rem] flex flex-col justify-center transition
                      ${fill.empty ? "bg-white/50 border-dashed border-ink/25" : hasMust ? "border-flag-blue" : "border-ink/20"}
                      ${selected ? "ring-2 ring-flag-blue" : "hover:shadow-md hover:-translate-y-px"}`}
                  >
                    {/* must-have — деликатно в правом верхнем углу */}
                    {hasMust ? (
                      <span className="absolute top-2.5 right-3 flex items-center gap-1.5 text-[11px] font-semibold leading-none rounded-full bg-white/80 px-1.5 py-0.5">
                        {cell.n_must_client ? <span className="text-flag-blue" title="must-have от клиента">★{cell.n_must_client}</span> : null}
                        {cell.n_must_expert ? <span className="text-purple-600" title="важное от эксперта">★{cell.n_must_expert}</span> : null}
                      </span>
                    ) : null}

                    {/* одна ось: название слева, цифра серифом справа — соразмерны */}
                    <div className="flex items-center justify-between gap-3">
                      <span
                        className="font-semibold leading-snug text-[14px] md:text-[15px]"
                        style={{ color: fill.empty ? "#8B877C" : fill.fg }}
                      >{s.name}</span>
                      {total > 0
                        ? <span className="shrink-0 font-display text-3xl md:text-[2rem] leading-none select-none" style={{ color: fill.fg }}>{total}</span>
                        : <span className="shrink-0 text-2xl leading-none text-ink/20">+</span>}
                    </div>

                    {/* доля пробелов — тонкая песочная полоска внизу (граница цветов текста не касается) */}
                    {!fill.empty && fill.greyShare > 0 && (
                      <div
                        className="absolute left-5 right-5 bottom-2 h-1 rounded-full overflow-hidden"
                        style={{ background: "rgba(0,0,0,0.08)" }}
                        title={`пробелы: ${Math.round(fill.greyShare * 100)}%`}
                      >
                        <div className="h-full rounded-full" style={{ width: `${Math.max(6, Math.round(fill.greyShare * 100))}%`, background: "hsl(42, 30%, 72%)" }} />
                      </div>
                    )}
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
