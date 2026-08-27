import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
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
const TEXT_DRAFT_KEY = (clientId: string) => `add-data-text:${clientId}`;

/**
 * "Инфа от клиента" — факты, присланные клиентом лично. Помечаются must-have
 * (синий цвет), идут через канал offline_interview (источник "От клиента"),
 * и получают большой вес в Deliver. Два способа: вписать вручную ИЛИ загрузить
 * файл (PDF, в т.ч. скан) — Claude vision разбирает его автоматом и раскладывает
 * факты по матрице (все слои L1–L8), аналитик правит/отмечает → коммит синими.
 */
export default function IngestClientFacts({ clientId, onJumpToCell, layers }: Props) {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const subsectionOptions = (layers ?? []).flatMap(L =>
    L.subsections.map(s => ({ id: s.id, label: `${s.id} — ${subsectionNameRu(s.id, s.name)} (${layerNameRu(L.id, L.name)})` }))
  );

  const initialMode = params.get("mode") === "file" ? "file" : "manual";
  const [mode, setMode] = useState<"manual" | "file">(initialMode);
  const [sourceTitle, setSourceTitle] = useState("От клиента");
  const [done, setDone] = useState<{ written: number; firstSid?: string } | null>(null);

  const invalidate = (firstSid?: string, written = 0) => {
    qc.invalidateQueries({ queryKey: ["matrix", clientId] });
    qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    qc.invalidateQueries({ queryKey: ["punch", clientId] });
    setDone({ written, firstSid });
  };

  // ── manual mode ──────────────────────────────────────────────────────────
  const [rows, setRows] = useState<DraftRow[]>([{ ...EMPTY_ROW }]);
  useEffect(() => {
    if (params.get("prefill") !== "add-data") return;
    const draft = localStorage.getItem(TEXT_DRAFT_KEY(clientId));
    if (!draft) return;
    setMode("manual");
    setRows([{ ...EMPTY_ROW, text: draft }]);
    localStorage.removeItem(TEXT_DRAFT_KEY(clientId));
  }, [clientId, params]);
  const manualCommit = useMutation({
    mutationFn: (facts: DraftRow[]) => api.ingestClientFacts(clientId, sourceTitle.trim() || "От клиента", facts),
    onSuccess: (res) => {
      const firstSid = rows.find(r => r.text.trim() && r.subsection_id)?.subsection_id;
      invalidate(firstSid, res.written?.length ?? 0);
      setRows([{ ...EMPTY_ROW }]);
    },
  });
  const manualValid = rows.filter(r => r.text.trim() && r.subsection_id);
  const setRow = (i: number, patch: Partial<DraftRow>) =>
    setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  // ── file mode (auto-parse) ─────────────────────────────────────────────────
  const fileRef = useRef<HTMLInputElement>(null);
  const [cands, setCands] = useState<DraftRow[] | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const previewMut = useMutation({
    mutationFn: (file: File) => api.clientFactsPreview(clientId, file),
    onSuccess: (r) => {
      setSourceTitle(r.source_title || "От клиента");
      const c: DraftRow[] = r.candidates.map(x => ({
        text: x.text, subsection_id: x.suggested_subsection_id || "", flag: x.suggested_flag,
      }));
      setCands(c);
      setAccepted(new Set(c.map((_, i) => i)));
      setDone(null);
    },
  });
  const fileCommit = useMutation({
    mutationFn: () => api.ingestClientFacts(clientId, sourceTitle.trim() || "От клиента",
      (cands ?? []).filter((_, i) => accepted.has(i)).map(c => ({
        text: c.text, subsection_id: c.subsection_id, flag: c.flag,
      }))),
    onSuccess: (res) => {
      const firstSid = (cands ?? []).find((c, i) => accepted.has(i) && c.subsection_id)?.subsection_id;
      invalidate(firstSid, res.written?.length ?? 0);
      setCands(null); setAccepted(new Set());
    },
  });
  const toggle = (i: number) => setAccepted(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const setCand = (i: number, patch: Partial<DraftRow>) =>
    setCands(cs => (cs ?? []).map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const acceptedValid = (cands ?? []).filter((c, i) => accepted.has(i) && c.text.trim() && c.subsection_id).length;

  return (
    <div className="p-5 max-w-[820px] mx-auto space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold text-ink flex items-center gap-2">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-flag-blue" /> Инфа от клиента
        </h2>
        <p className="text-sm text-ink-mute mt-1">
          Факты, присланные клиентом лично. Помечаются как <span className="text-flag-blue font-medium">★ обязательные</span> (синий)
          и получают большой вес в Deliver. Канал — offline_interview, провенанс — название источника.
        </p>
      </div>

      <div className="bg-white rounded-lg border border-ink-line p-5 space-y-4">
        {/* mode toggle */}
        <div className="inline-flex text-xs border border-ink-line rounded-xl overflow-hidden bg-[#f6f6f1]">
          <button onClick={() => { setMode("manual"); setDone(null); }}
            className={`px-3.5 py-1.5 transition ${mode === "manual" ? "bg-ink text-white" : "text-ink-mute hover:bg-white"}`}>Вписать вручную</button>
          <button onClick={() => { setMode("file"); setDone(null); }}
            className={`px-3.5 py-1.5 transition ${mode === "file" ? "bg-ink text-white" : "text-ink-mute hover:bg-white"}`}>Загрузить файл</button>
        </div>

        <label className="block space-y-2">
          <span className="text-xs font-medium text-ink-mute">Источник</span>
          <input
            value={sourceTitle}
            onChange={e => setSourceTitle(e.target.value)}
            placeholder="От клиента"
            className="w-full text-sm border border-ink-line rounded-xl px-3 py-2 bg-white"
          />
        </label>
      </div>

      {mode === "manual" && (
        <>
          <div className="space-y-3">
            {rows.map((r, i) => (
              <div key={i} className="bg-white rounded-lg border border-ink-line p-5 space-y-3">
                <div className="flex items-start gap-2">
                  <span className="inline-block w-2 h-2 rounded-full bg-flag-blue mt-2 shrink-0" />
                  <textarea
                    value={r.text}
                    onChange={e => setRow(i, { text: e.target.value })}
                    placeholder="Текст факта от клиента…"
                    rows={2}
                    className="flex-1 text-sm border border-ink-line rounded-xl px-3 py-2 resize-y"
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
                    className={`text-xs border border-ink-line rounded-xl px-2 py-1.5 bg-white max-w-[22rem]
                      ${r.subsection_id ? "text-ink" : "text-ink-mute"}`}
                  >
                    <option value="">— ячейка матрицы —</option>
                    {subsectionOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
                  </select>
                  <select
                    value={r.flag}
                    onChange={e => setRow(i, { flag: e.target.value })}
                    className="text-xs border border-ink-line rounded-xl px-2 py-1.5 bg-white"
                  >
                    <option value="green">факт</option>
                    <option value="red">риск</option>
                    <option value="grey">пробел</option>
                  </select>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setRows(rs => [...rs, { ...EMPTY_ROW }])}
              className="text-xs text-ink-mute hover:text-ink border border-ink-line rounded-xl px-2.5 py-1.5"
            >+ ещё факт</button>
            <button
              onClick={() => manualCommit.mutate(manualValid)}
              disabled={manualValid.length === 0 || manualCommit.isPending}
              className="text-sm bg-flag-blue text-white rounded-xl px-4 py-2 disabled:opacity-40"
            >{manualCommit.isPending ? "Сохраняю…" : `Сохранить ${manualValid.length || ""} факт(ов)`}</button>
          </div>
          {manualCommit.isError && (
            <div className="text-sm text-flag-red">Ошибка: {(manualCommit.error as Error).message}</div>
          )}
        </>
      )}

      {mode === "file" && (
        <>
          {!cands && (
            <div className="bg-white rounded-lg border border-ink-line p-5 text-center space-y-3">
              <p className="text-sm text-ink-mute">
                Загрузите файл, который прислал клиент (PDF, в т.ч. скан). Распознаем автоматически
                и разложим факты по матрице — вы проверите перед записью.
              </p>
              <input ref={fileRef} type="file" accept="application/pdf" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) previewMut.mutate(f); e.target.value = ""; }} />
              <button onClick={() => fileRef.current?.click()} disabled={previewMut.isPending}
                className="text-sm bg-ink text-white rounded-xl px-4 py-2 disabled:opacity-40">
                {previewMut.isPending ? "Распознаю документ…" : "Выбрать PDF"}
              </button>
              {previewMut.isError && (
                <div className="text-sm text-flag-red">Ошибка: {(previewMut.error as Error).message}</div>
              )}
            </div>
          )}

          {cands && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-mute">
                  Распознано фактов: {cands.length}. Отметьте нужные, поправьте ячейку/флаг.
                </span>
                <button onClick={() => { setCands(null); setAccepted(new Set()); }}
                  className="text-xs text-ink-mute hover:text-ink">← другой файл</button>
              </div>
              {cands.length === 0 && (
                <div className="text-sm text-ink-mute bg-white rounded-lg border border-ink-line p-5">
                  Из документа не извлеклось фактов. Попробуйте другой файл или впишите вручную.
                </div>
              )}
              {cands.map((c, i) => (
                <div key={i} className={`border rounded-lg p-3 bg-white space-y-2
                  ${accepted.has(i) ? "border-flag-blue/40" : "border-ink-line opacity-60"}`}>
                  <div className="flex items-start gap-2">
                    <input type="checkbox" checked={accepted.has(i)} onChange={() => toggle(i)} className="mt-1.5 accent-flag-blue" />
                    <textarea
                      value={c.text}
                      onChange={e => setCand(i, { text: e.target.value })}
                      rows={2}
                      className="flex-1 text-sm border border-ink-line rounded-xl px-3 py-2 resize-y"
                    />
                  </div>
                  <div className="flex items-center gap-2 pl-6">
                    <select
                      value={c.subsection_id}
                      onChange={e => setCand(i, { subsection_id: e.target.value })}
                      className={`text-xs border border-ink-line rounded-xl px-2 py-1.5 bg-white max-w-[22rem]
                        ${c.subsection_id ? "text-ink" : "text-ink-mute"}`}
                    >
                      <option value="">— ячейка матрицы —</option>
                      {subsectionOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
                    </select>
                    <select
                      value={c.flag}
                      onChange={e => setCand(i, { flag: e.target.value })}
                      className="text-xs border border-ink-line rounded-xl px-2 py-1.5 bg-white"
                    >
                      <option value="green">факт</option>
                      <option value="red">риск</option>
                      <option value="grey">пробел</option>
                    </select>
                  </div>
                </div>
              ))}
              {cands.length > 0 && (
                <button
                  onClick={() => fileCommit.mutate()}
                  disabled={acceptedValid === 0 || fileCommit.isPending}
                  className="text-sm bg-flag-blue text-white rounded-xl px-4 py-2 disabled:opacity-40"
                >{fileCommit.isPending ? "Вношу…" : `Внести ${acceptedValid || ""} синими в матрицу`}</button>
              )}
              {fileCommit.isError && (
                <div className="text-sm text-flag-red">Ошибка: {(fileCommit.error as Error).message}</div>
              )}
            </div>
          )}
        </>
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
