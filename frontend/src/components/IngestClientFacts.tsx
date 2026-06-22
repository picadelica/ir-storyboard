import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Layer } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
  layers?: Layer[];
}

interface DraftRow {
  text: string;
  subsection_id: string;
  flag: string;
}

const EMPTY_ROW: DraftRow = { text: "", subsection_id: "", flag: "green" };

/**
 * "Инфа от клиента" — факты, присланные клиентом лично. Помечаются must-have
 * (синий цвет), идут через канал offline_interview (источник "От клиента"),
 * и получают большой вес в Deliver. Аналитик просто вставляет факт + выбирает
 * ячейку матрицы.
 */
export default function IngestClientFacts({ clientId, onJumpToCell, layers }: Props) {
  const qc = useQueryClient();
  const subsectionOptions = (layers ?? []).flatMap(L =>
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${s.name} (${L.name})` }))
  );

  const [sourceTitle, setSourceTitle] = useState("От клиента");
  const [rows, setRows] = useState<DraftRow[]>([{ ...EMPTY_ROW }]);
  const [done, setDone] = useState<{ written: number; firstSid?: string } | null>(null);

  const commit = useMutation({
    mutationFn: (facts: DraftRow[]) => api.ingestClientFacts(clientId, sourceTitle.trim() || "От клиента", facts),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
      const firstSid = rows.find(r => r.text.trim() && r.subsection_id)?.subsection_id;
      setDone({ written: res.written?.length ?? 0, firstSid });
      setRows([{ ...EMPTY_ROW }]);
    },
  });

  const valid = rows.filter(r => r.text.trim() && r.subsection_id);
  const setRow = (i: number, patch: Partial<DraftRow>) =>
    setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-ink flex items-center gap-2">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-flag-blue" /> Инфа от клиента
        </h2>
        <p className="text-sm text-ink-mute mt-1">
          Факты, присланные клиентом лично. Помечаются как <span className="text-flag-blue font-medium">★ must-have</span> (синий)
          и получают большой вес в Deliver. Канал — offline_interview, провенанс — название источника.
        </p>
      </div>

      <label className="block">
        <span className="text-xs text-ink-mute">Источник</span>
        <input
          value={sourceTitle}
          onChange={e => setSourceTitle(e.target.value)}
          placeholder="От клиента"
          className="mt-1 w-full text-sm border border-ink-line rounded px-2 py-1.5 bg-white"
        />
      </label>

      <div className="space-y-3">
        {rows.map((r, i) => (
          <div key={i} className="border border-ink-line rounded-lg p-3 bg-white space-y-2">
            <div className="flex items-start gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-flag-blue mt-2 shrink-0" />
              <textarea
                value={r.text}
                onChange={e => setRow(i, { text: e.target.value })}
                placeholder="Текст факта от клиента…"
                rows={2}
                className="flex-1 text-sm border border-ink-line rounded px-2 py-1.5 resize-y"
              />
              {rows.length > 1 && (
                <button
                  onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}
                  className="text-[11px] text-red-600 hover:text-red-800 px-1.5 py-0.5 rounded shrink-0"
                >убрать</button>
              )}
            </div>
            <div className="flex items-center gap-2 pl-4">
              <select
                value={r.subsection_id}
                onChange={e => setRow(i, { subsection_id: e.target.value })}
                className={`text-xs border border-ink-line rounded px-1.5 py-1 bg-white max-w-[22rem]
                  ${r.subsection_id ? "text-ink" : "text-ink-mute"}`}
              >
                <option value="">— ячейка матрицы —</option>
                {subsectionOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
              <select
                value={r.flag}
                onChange={e => setRow(i, { flag: e.target.value })}
                className="text-xs border border-ink-line rounded px-1.5 py-1 bg-white"
              >
                <option value="green">green</option>
                <option value="red">red</option>
                <option value="grey">grey</option>
              </select>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => setRows(rs => [...rs, { ...EMPTY_ROW }])}
          className="text-xs text-ink-mute hover:text-ink border border-ink-line rounded px-2.5 py-1.5"
        >+ ещё факт</button>
        <button
          onClick={() => commit.mutate(valid)}
          disabled={valid.length === 0 || commit.isPending}
          className="text-sm bg-flag-blue text-white rounded px-4 py-1.5 disabled:opacity-40"
        >{commit.isPending ? "Сохраняю…" : `Сохранить ${valid.length || ""} факт(ов)`}</button>
      </div>

      {commit.isError && (
        <div className="text-sm text-flag-red">Ошибка: {(commit.error as Error).message}</div>
      )}
      {done && (
        <div className="text-sm text-emerald-700 flex items-center gap-3">
          ✓ Записано фактов: {done.written}
          {done.firstSid && (
            <button onClick={() => onJumpToCell(done.firstSid!)} className="text-flag-blue hover:underline">
              перейти в матрицу →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
