import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { MatrixExport } from "../types";
import FlagDot from "./FlagDot";

function Star({ star }: { star: "blue" | "purple" | null }) {
  if (!star) return <span className="inline-block w-[14px]" />;
  const color = star === "blue" ? "text-flag-blue" : "text-purple-600";
  const title = star === "blue" ? "must-have от клиента (обязательно)" : "важное от эксперта (приоритет)";
  return <span className={`text-[13px] leading-none ${color}`} title={title}>★</span>;
}

export default function ExportView({ clientId }: { clientId: string }) {
  const [copied, setCopied] = useState(false);
  const [showFormat, setShowFormat] = useState(false);
  const q = useQuery<MatrixExport>({
    queryKey: ["matrix-export", clientId],
    queryFn: () => api.matrixExport(clientId),
  });
  const formatQ = useQuery<string>({
    queryKey: ["matrix-format-md", clientId],
    queryFn: () => api.matrixFormatMd(clientId),
    enabled: showFormat,
  });

  if (q.isLoading) return <div className="p-6 text-sm text-ink-mute">Готовлю выгрузку…</div>;
  if (q.isError || !q.data) return <div className="p-6 text-sm text-red-600">Не удалось собрать выгрузку.</div>;

  const data = q.data;
  const meta = data.export;

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };

  // группируем карточки по номеру ячейки для читаемого превью
  const byCell: Record<string, typeof data.cards> = {};
  for (const c of data.cards) (byCell[c.matrix_no] ||= []).push(c);
  const cellNos = Object.keys(byCell);

  return (
    <div className="p-5 max-w-4xl space-y-5">
      {/* шапка + действия */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Выгрузка матрицы</h2>
          <p className="text-[13px] text-ink-mute mt-1 max-w-2xl leading-snug">{meta.description}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowFormat(v => !v)}
            className="text-xs text-ink-mute border border-ink-line rounded px-2.5 py-1.5 hover:bg-slate-50"
          >{showFormat ? "Скрыть описание" : "Описание формата (md)"}</button>
          <button
            onClick={copyJson}
            className="text-xs text-ink-mute border border-ink-line rounded px-2.5 py-1.5 hover:bg-slate-50"
          >{copied ? "Скопировано ✓" : "Скопировать JSON"}</button>
          <button
            onClick={() => api.downloadMatrixExport(clientId, meta.client_name).catch(() => {})}
            className="text-xs text-white bg-ink rounded px-3 py-1.5 hover:bg-black"
          >Скачать JSON</button>
        </div>
      </div>

      {/* markdown-описание формата JSON (чтобы заказчик мог разобрать JSON) */}
      {showFormat && (
        <section className="rounded-lg border border-ink-line bg-white">
          <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
            <div className="text-[11px] uppercase tracking-wide text-ink-mute">Описание формата JSON (передать заказчику)</div>
            <button
              onClick={() => api.downloadMatrixFormat(clientId, meta.client_name).catch(() => {})}
              className="text-xs text-white bg-ink rounded px-3 py-1 hover:bg-black"
            >Скачать .md</button>
          </div>
          {formatQ.isLoading ? (
            <div className="px-3.5 pb-3 text-sm text-ink-mute">Готовлю описание…</div>
          ) : formatQ.isError ? (
            <div className="px-3.5 pb-3 text-sm text-red-600">Не удалось собрать описание.</div>
          ) : (
            <pre className="px-3.5 pb-3.5 text-[12px] leading-snug text-ink whitespace-pre-wrap font-mono max-h-[28rem] overflow-auto">{formatQ.data}</pre>
          )}
        </section>
      )}

      {/* основное описание выгрузки */}
      <section className="rounded-lg border border-ink-line p-3.5 bg-white">
        <div className="text-[11px] uppercase tracking-wide text-ink-mute mb-2">Описание выгрузки</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <div><span className="text-ink-mute">Клиент:</span> <span className="font-medium">{meta.client_name}</span></div>
          <div><span className="text-ink-mute">Карточек:</span> <span className="font-medium">{meta.card_count}</span></div>
          {meta.sector && <div><span className="text-ink-mute">Сектор:</span> {meta.sector}</div>}
          {meta.one_liner && <div className="col-span-2"><span className="text-ink-mute">Кратко:</span> {meta.one_liner}</div>}
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-3 pt-3 border-t border-ink-line/60 text-[12px]">
          <span className="text-ink-mute">Цвет карточки:</span>
          <span className="flex items-center gap-1.5"><FlagDot flag="green" /> подтверждено</span>
          <span className="flex items-center gap-1.5"><FlagDot flag="red" /> риск</span>
          <span className="flex items-center gap-1.5"><FlagDot flag="grey" /> пробел</span>
          <span className="text-ink-mute ml-2">Звезда:</span>
          <span className="flex items-center gap-1"><Star star="blue" /> клиент</span>
          <span className="flex items-center gap-1"><Star star="purple" /> эксперт</span>
        </div>
      </section>

      {/* карточка компании */}
      {data.company_card && (
        <section className="rounded-lg border border-ink-line p-3.5 bg-white">
          <div className="text-[11px] uppercase tracking-wide text-ink-mute mb-2">Карточка компании</div>
          <div className="text-sm font-semibold">{data.company_card.name}
            {data.company_card.role && <span className="ml-2 text-ink-mute font-normal">· {data.company_card.role}</span>}
          </div>
          {data.company_card.facts.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[13px]">
              {data.company_card.facts.map((f, i) => (
                <li key={i} className="flex gap-2">
                  {f.section && <span className="text-[10px] uppercase text-ink-mute/70 shrink-0 w-16 pt-0.5">{f.section}</span>}
                  <span><span className="text-ink-mute">{f.key && `${f.key}: `}</span>{f.value}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* состав карточек */}
      <section className="rounded-lg border border-ink-line bg-white">
        <div className="text-[11px] uppercase tracking-wide text-ink-mute px-3.5 pt-3 pb-1">
          Карточки — состав ({meta.card_count})
        </div>
        <div className="divide-y divide-ink-line/60">
          {cellNos.map(no => (
            <div key={no} className="px-3.5 py-2.5">
              <div className="text-[11px] text-ink-mute font-mono mb-1.5">
                {no} · {byCell[no][0].subsection_name}
              </div>
              <div className="space-y-1.5">
                {byCell[no].map(c => (
                  <div key={c.fact_id} className="flex items-start gap-2">
                    <FlagDot flag={c.card_color} className="mt-1.5" />
                    <Star star={c.star} />
                    <div className="min-w-0">
                      {c.title && <span className="text-[13px] font-semibold text-ink mr-1.5">{c.title}</span>}
                      <span className="text-[13px] text-ink leading-snug">{c.text}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {cellNos.length === 0 && <div className="px-3.5 py-4 text-sm text-ink-mute">В матрице ещё нет карточек.</div>}
        </div>
      </section>
    </div>
  );
}
