import { Fragment, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type { Scorecard, Fact, Flag } from "../types";
import FlagDot from "./FlagDot";

type Picked = { flag: Flag; sids: string[]; title: string };

const FLAG_WORD: Record<Flag, string> = { green: "зелёные", red: "красные", grey: "серые (пробелы)" };
const FLAG_TXT: Record<Flag, string> = { green: "text-flag-green", red: "text-flag-red", grey: "text-flag-grey" };

export default function ScorecardView({ clientId, onSelectCell }: { clientId: string; onSelectCell?: (sid: string) => void }) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const sc = useQuery<Scorecard>({
    queryKey: ["scorecard", clientId],
    queryFn: () => api.scorecard(clientId),
  });
  if (sc.isLoading) return <div className="p-6 text-sm text-ink-mute">Загрузка…</div>;
  if (!sc.data) return null;

  const { rows, totals } = sc.data;
  const byLayer = new Map<number, { layer_name: string; rows: typeof rows }>();
  for (const r of rows) {
    if (!byLayer.has(r.layer_id)) byLayer.set(r.layer_id, { layer_name: r.layer_name, rows: [] });
    byLayer.get(r.layer_id)!.rows.push(r);
  }
  const sortedLayers = Array.from(byLayer.entries()).sort(([a], [b]) => a - b);

  // все ячейки, где есть факты данного флага (для клика по тоталу)
  const sidsForFlag = (flag: Flag) => rows
    .filter(r => (flag === "green" ? r.n_green : flag === "red" ? r.n_red : r.n_grey) > 0)
    .map(r => r.subsection_id);

  // клик по цифре ячейки → открыть полноценный drawer ячейки справа (как в матрице)
  const Num = ({ r, flag, n }: { r: typeof rows[number]; flag: Flag; n: number }) =>
    n > 0 ? (
      <button onClick={() => onSelectCell?.(r.subsection_id)}
        className={`font-mono ${FLAG_TXT[flag]} hover:underline`} title={`Открыть карточки ячейки ${r.subsection_id} (${FLAG_WORD[flag]})`}>{n}</button>
    ) : <span className="font-mono text-ink-mute/40">0</span>;

  return (
    <div className="p-5 max-w-5xl space-y-5">
      <h2 className="text-lg font-semibold">Оценка фактов</h2>

      <div className="grid grid-cols-4 gap-3">
        <Stat label="Green facts" value={totals.green} accent="text-flag-green"
          onClick={totals.green ? () => setPicked({ flag: "green", sids: sidsForFlag("green"), title: "Все зелёные карточки" }) : undefined} />
        <Stat label="Red flags" value={totals.red} accent="text-flag-red"
          onClick={totals.red ? () => setPicked({ flag: "red", sids: sidsForFlag("red"), title: "Все красные карточки" }) : undefined} />
        <Stat label="Explicit gaps" value={totals.grey} accent="text-flag-grey"
          onClick={totals.grey ? () => setPicked({ flag: "grey", sids: sidsForFlag("grey"), title: "Все серые карточки (пробелы)" }) : undefined} />
        <Stat label="Untouched cells" value={totals.empty_cells} accent="text-slate-400" />
      </div>

      <div className="bg-white rounded-lg border border-ink-line overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] font-mono uppercase text-ink-mute">
            <tr>
              <th className="text-left px-3 py-2">Ячейка</th>
              <th className="text-left px-3 py-2">Слой → позиция</th>
              <th className="text-right px-3 py-2">🟢</th>
              <th className="text-right px-3 py-2">🔴</th>
              <th className="text-right px-3 py-2">⚫ пробелы</th>
              <th className="text-left px-3 py-2">Обновлено</th>
            </tr>
          </thead>
          <tbody>
            {sortedLayers.map(([lid, group]) => (
              <Fragment key={lid}>
                <tr className="bg-slate-100">
                  <td colSpan={6} className="px-3 py-1.5 text-xs font-semibold">L{lid} {layerNameRu(lid, group.layer_name)}</td>
                </tr>
                {group.rows.map(r => (
                  <tr key={r.subsection_id} className="border-t border-ink-line">
                    <td className="px-3 py-2 font-mono text-xs">{r.subsection_id}</td>
                    <td className="px-3 py-2">{subsectionNameRu(r.subsection_id, r.subsection_name)}</td>
                    <td className="px-3 py-2 text-right"><Num r={r} flag="green" n={r.n_green} /></td>
                    <td className="px-3 py-2 text-right"><Num r={r} flag="red" n={r.n_red} /></td>
                    <td className="px-3 py-2 text-right"><Num r={r} flag="grey" n={r.n_grey} /></td>
                    <td className="px-3 py-2 text-xs text-ink-mute">{(r.last_update ?? "").slice(0, 10) || "—"}</td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {picked && <CardSet clientId={clientId} picked={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}

// Набор карточек выбранного флага: тянем факты нужных ячеек параллельно, фильтруем.
function CardSet({ clientId, picked, onClose }: { clientId: string; picked: Picked; onClose: () => void }) {
  const results = useQueries({
    queries: picked.sids.map(sid => ({
      queryKey: ["cellFacts", clientId, sid],
      queryFn: () => api.cellFacts(clientId, sid),
    })),
  });
  const loading = results.some(q => q.isLoading);
  const facts: (Fact & { _sid: string })[] = results.flatMap((q, i) =>
    (q.data || [])
      .filter(f => f.flag === picked.flag && f.state !== "rejected")
      .map(f => ({ ...f, _sid: picked.sids[i] })));

  return (
    <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10" onClick={onClose}>
      <div className="bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-ink-line">
          <div className="flex items-center gap-2">
            <FlagDot flag={picked.flag} size={10} />
            <h3 className="text-sm font-semibold">{picked.title}</h3>
            {!loading && <span className="text-xs text-ink-mute">· {facts.length}</span>}
          </div>
          <button onClick={onClose} className="text-ink-mute hover:text-ink text-sm">✕</button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-3 space-y-2">
          {loading ? (
            <div className="text-sm text-ink-mute px-1 py-2">Загружаю карточки…</div>
          ) : facts.length === 0 ? (
            <div className="text-sm text-ink-mute px-1 py-2">Нет карточек.</div>
          ) : facts.map(f => (
            <div key={f.id} className="rounded-lg border border-ink-line p-3">
              <div className="flex items-center gap-2 mb-1">
                <FlagDot flag={f.flag} size={9} />
                <span className="text-[11px] font-mono text-ink-mute">{f._sid} · #{f.id}</span>
                {f.must_have && <span className={`text-[12px] leading-none ${f.must_have_by === "expert" ? "text-purple-600" : "text-flag-blue"}`}>★</span>}
              </div>
              {f.title && <div className="text-sm font-semibold text-ink leading-tight mb-0.5">{f.title}</div>}
              <div className="text-sm text-ink leading-snug">{f.text}</div>
              {f.flag !== "green" && f.rationale && (
                <div className={`mt-1.5 text-xs border-l-2 pl-2 leading-snug ${f.flag === "red" ? "border-flag-red/60 text-flag-red" : "border-flag-grey/60 text-ink-mute"}`}>
                  {f.rationale}
                </div>
              )}
              {f.source_url && (
                <a href={f.source_url} target="_blank" rel="noreferrer" className="inline-block mt-1.5 text-[11px] text-blue-600 hover:underline" title={f.source_title || f.source_url}>
                  источник ↗
                </a>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, accent, onClick }: { label: string; value: number; accent: string; onClick?: () => void }) {
  const body = (
    <>
      <div className="text-xs text-ink-mute uppercase tracking-wide">{label}</div>
      <div className={`text-3xl font-semibold mt-1 ${accent}`}>{value}</div>
    </>
  );
  return onClick ? (
    <button onClick={onClick} title="Открыть карточки" className="text-left bg-white rounded-lg border border-ink-line p-4 hover:border-ink/30 hover:shadow-sm transition">{body}</button>
  ) : (
    <div className="bg-white rounded-lg border border-ink-line p-4">{body}</div>
  );
}
