import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Scorecard } from "../types";

export default function ScorecardView({ clientId }: { clientId: string }) {
  const sc = useQuery<Scorecard>({
    queryKey: ["scorecard", clientId],
    queryFn: () => api.scorecard(clientId),
  });
  if (sc.isLoading) return <div className="p-6 text-sm text-ink-mute">Loading…</div>;
  if (!sc.data) return null;

  const { rows, totals } = sc.data;
  // group by layer
  const byLayer = new Map<number, { layer_name: string; rows: typeof rows }>();
  for (const r of rows) {
    if (!byLayer.has(r.layer_id))
      byLayer.set(r.layer_id, { layer_name: r.layer_name, rows: [] });
    byLayer.get(r.layer_id)!.rows.push(r);
  }
  const sortedLayers = Array.from(byLayer.entries()).sort(([a], [b]) => a - b);

  return (
    <div className="p-5 max-w-5xl space-y-5">
      <h2 className="text-lg font-semibold">Green-flag scorecard</h2>

      <div className="grid grid-cols-4 gap-3">
        <Stat label="Green facts"  value={totals.green} accent="text-flag-green" />
        <Stat label="Red flags"    value={totals.red}   accent="text-flag-red" />
        <Stat label="Explicit gaps" value={totals.grey} accent="text-flag-grey" />
        <Stat label="Untouched cells" value={totals.empty_cells} accent="text-slate-400" />
      </div>

      <div className="bg-white rounded-lg border border-ink-line overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] font-mono uppercase text-ink-mute">
            <tr>
              <th className="text-left px-3 py-2">Cell</th>
              <th className="text-left px-3 py-2">Layer → Subsection</th>
              <th className="text-right px-3 py-2">🟢</th>
              <th className="text-right px-3 py-2">🔴</th>
              <th className="text-right px-3 py-2">⚫ gap</th>
              <th className="text-left px-3 py-2">Last update</th>
            </tr>
          </thead>
          <tbody>
            {sortedLayers.map(([lid, group]) => (
              <Fragment key={lid}>
                <tr className="bg-slate-100">
                  <td colSpan={6} className="px-3 py-1.5 text-xs font-semibold">
                    L{lid} {group.layer_name}
                  </td>
                </tr>
                {group.rows.map(r => (
                  <tr key={r.subsection_id} className="border-t border-ink-line">
                    <td className="px-3 py-2 font-mono text-xs">{r.subsection_id}</td>
                    <td className="px-3 py-2">{r.subsection_name}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.n_green}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.n_red}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.n_grey}</td>
                    <td className="px-3 py-2 text-xs text-ink-mute">
                      {(r.last_update ?? "").slice(0, 10) || "—"}
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="bg-white rounded-lg border border-ink-line p-4">
      <div className="text-xs text-ink-mute uppercase tracking-wide">{label}</div>
      <div className={`text-3xl font-semibold mt-1 ${accent}`}>{value}</div>
    </div>
  );
}
