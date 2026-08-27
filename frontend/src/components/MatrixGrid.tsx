import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { HintTarget } from "./Hint";
import EvidenceBadges from "./EvidenceBadges";
import { cellFill, recordMax } from "../lib/cellFill";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import {
  MATRIX_BODY,
  MATRIX_CELL,
  MATRIX_CELL_ID,
  MATRIX_CELL_IDLE,
  MATRIX_CELL_SELECTED,
  MATRIX_CELL_TITLE,
  MATRIX_CELL_VALUE,
  MATRIX_GRID,
  MATRIX_HEADER,
  MATRIX_LAYER_BADGE,
  MATRIX_LAYER_COL,
  MATRIX_LAYER_COLUMN_WIDTH,
  MATRIX_PAGE,
  MATRIX_PAGE_PADDING,
  MATRIX_PRESENT_PADDING,
  MATRIX_ROW,
} from "./matrixFrame";
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
    return <div className="p-6 text-sm text-ink-mute">Загружаю матрицу…</div>;
  }
  if (!layers.data || !cells.data) {
    return <div className="p-6 text-sm text-red-600">Не удалось загрузить.</div>;
  }

  const cellBySid = new Map(cells.data.map(c => [c.subsection_id, c]));
  // максимум записей в ячейке — база для 10-ступенчатой шкалы заливки
  const maxRecords = recordMax(cells.data.map(cellTotal));

  const queue = review.data ?? [];

  return (
    <div className={`${MATRIX_PAGE} ${present ? MATRIX_PRESENT_PADDING : MATRIX_PAGE_PADDING}`}>
      <div className={MATRIX_HEADER}>
        <div className="text-[12px] text-ink-mute">
          {queue.length > 0 ? `${queue.length} черновиков ждут одобрения` : "Матрица знаний"}
        </div>
        {!present && queue.length > 0 && (
          <button onClick={() => setQueueOpen(o => !o)}
            className="text-xs px-3 py-1.5 rounded-xl border border-[#f0c86b] bg-[#fff4d8] text-[#5b4215] hover:bg-[#fff0c8]">
            Черновики {queueOpen ? "▴" : "▾"}
          </button>
        )}
      </div>

      {!present && queue.length > 0 && queueOpen && (
        <div className="absolute left-5 right-5 top-[72px] z-30 max-h-80 overflow-y-auto border border-[#f0c86b] bg-[#fff9ea] rounded-2xl shadow-lg">
            <ul className="divide-y divide-[#f0c86b]/50">
              {queue.map(f => (
                <li key={f.id} className="flex items-start gap-3 px-4 py-2.5">
                  <span className="shrink-0 font-mono text-[11px] text-[#8a671e] pt-0.5">{f.subsection_id}</span>
                  <span className="flex-1 text-[13px] text-ink leading-snug">{f.text}</span>
                  <div className="shrink-0 flex items-center gap-2">
                    {canApprove && (
                      <button onClick={() => approve.mutate(f.id)} disabled={approve.isPending}
                        className="text-[11px] px-2.5 py-1 rounded-lg bg-[#98c61b] text-[#20221f] font-bold hover:brightness-105 disabled:opacity-50">
                        одобрить</button>
                    )}
                    <button onClick={() => onSelectCell(f.subsection_id)}
                      className="text-[11px] text-[#136080] hover:underline">ячейка →</button>
                  </div>
                </li>
              ))}
            </ul>
        </div>
      )}

      <div
        className={`${MATRIX_BODY} ${MATRIX_GRID}`}
        style={{ gridTemplateRows: `repeat(${layers.data.length}, minmax(0, 1fr))` }}
      >
        {layers.data.map(L => (
          (() => {
            const layerName = layerNameRu(L.id, L.name);
            return (
          <div
            key={L.id}
            className={MATRIX_ROW}
            style={{ gridTemplateColumns: `${MATRIX_LAYER_COLUMN_WIDTH} repeat(${L.subsections.length}, minmax(0, 1fr))` }}
          >
            {/* Колонка названий слоёв — компактный якорь строки */}
            <HintTarget
              title={`${L.id}. ${layerName}`}
              body={`Крупный тематический уровень матрицы. В этой строке собраны позиции раздела «${layerName}».`}
            >
              <div
                className={MATRIX_LAYER_COL}
              >
                <span className={MATRIX_LAYER_BADGE}>{L.id}</span>
              </div>
            </HintTarget>

            {/* Cells in this layer */}
            <>
              {L.subsections.map(s => {
                const cell = cellBySid.get(s.id);
                if (!cell) return null;
                const subsectionName = subsectionNameRu(s.id, s.name);
                const total = cellTotal(cell);
                // красный свёрнут в серый: считаем серые = grey + (legacy) red
                const fill = cellFill(cell.n_green || 0, (cell.n_grey || 0) + (cell.n_red || 0), maxRecords);
                const selected = selectedSubsectionId === s.id;
                const hasEvidence = !!(cell.n_must_client || cell.n_must_expert || cell.corroborated);
                return (
                  <button
                    key={s.id}
                    onClick={() => onSelectCell(s.id)}
                    style={fill.empty ? undefined : { background: fill.background }}
                      className={`${MATRIX_CELL}
                        ${fill.empty ? "bg-white" : ""}
                        ${selected
                        ? MATRIX_CELL_SELECTED
                        : MATRIX_CELL_IDLE}`}
                  >
                    {/* evidence badges — must-have + 2+ sources, same system as knowledge map */}
                    {hasEvidence ? (
                      <EvidenceBadges
                        mustClient={cell.n_must_client ?? 0}
                        mustExpert={cell.n_must_expert ?? 0}
                        corroborated={!!cell.corroborated}
                        className="absolute right-[10px] bottom-3"
                      />
                    ) : null}

                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <div className="min-w-0 flex-1 flex flex-col gap-0.5">
                        <span
                          className={MATRIX_CELL_ID}
                          style={{ color: fill.empty ? "#8B877C" : fill.fg }}
                        >{s.id}</span>
                        <span
                          className={MATRIX_CELL_TITLE}
                          style={{ color: fill.empty ? "#8B877C" : fill.fg }}
                        >{subsectionName}</span>
                      </div>

                      {total > 0
                        ? (
                          <HintTarget
                            title={`${s.id}. ${subsectionName}`}
                            body={`Здесь собрано ${total} фактов. Нажмите, чтобы открыть правую панель с фактами этой позиции.`}
                          >
                            <span
                              className={MATRIX_CELL_VALUE}
                              style={{ color: fill.fg }}
                            >{total}</span>
                          </HintTarget>
                        )
                        : (
                          <HintTarget
                            title={`${s.id}. ${subsectionName}`}
                            body="Здесь пока нет фактов. Нажмите, чтобы открыть позицию и посмотреть, что можно добавить."
                          >
                            <span className={`${MATRIX_CELL_VALUE} text-ink/25`}>0</span>
                          </HintTarget>
                        )}
                    </div>
                  </button>
                );
              })}
            </>
          </div>
            );
          })()
        ))}
      </div>
    </div>
  );
}
