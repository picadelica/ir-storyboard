import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { PunchList } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

export default function PunchListView({ clientId, onJumpToCell }: Props) {
  const punch = useQuery<PunchList>({
    queryKey: ["punch", clientId],
    queryFn: () => api.punchList(clientId),
  });

  if (punch.isLoading) return <div className="p-6 text-sm text-ink-mute">Loading…</div>;
  if (!punch.data) return null;
  const p = punch.data;
  const total = p.empty_cells.length + p.cells_with_known_gaps.length + p.thinly_covered.length;

  return (
    <div className="p-5 space-y-6 max-w-5xl">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Punch-list</h2>
        <div className="text-xs text-ink-mute">
          {total === 0 ? "✓ matrix is fully covered" : `${total} item${total === 1 ? "" : "s"}`}
        </div>
      </div>

      <Section
        title="1. Untouched cells (no facts at all)"
        empty="None — every cell has at least one fact."
        count={p.empty_cells.length}
      >
        <table className="w-full text-sm">
          <thead className="text-[10px] font-mono uppercase text-ink-mute">
            <tr><th className="text-left py-1.5 pr-3">Cell</th>
                <th className="text-left py-1.5 pr-3">Layer → Subsection</th>
                <th className="text-right py-1.5"></th></tr>
          </thead>
          <tbody>
            {p.empty_cells.map(c => (
              <tr key={c.subsection_id} className="border-t border-ink-line">
                <td className="py-2 pr-3 font-mono text-xs">{c.subsection_id}</td>
                <td className="py-2 pr-3">
                  <div className="text-sm">{c.layer_name} → {c.subsection_name}</div>
                </td>
                <td className="py-2 text-right">
                  <button onClick={() => onJumpToCell(c.subsection_id)}
                    className="text-xs px-2 py-1 hover:bg-slate-100 rounded text-blue-600">→ open</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section
        title="2. Explicit gaps (we know we don't know)"
        empty="No explicit gap markers — strong sign or sign of optimism, depending on viewpoint."
        count={p.cells_with_known_gaps.length}
      >
        <ul className="space-y-3">
          {p.cells_with_known_gaps.map(c => (
            <li key={c.subsection_id} className="bg-flag-grey-bg border border-flag-grey/40 rounded p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="text-xs font-medium">
                  <span className="font-mono">{c.subsection_id}</span> · {c.layer_name} → {c.subsection_name}
                </div>
                <button onClick={() => onJumpToCell(c.subsection_id)}
                  className="text-xs px-2 py-1 hover:bg-white rounded text-blue-600">→ open</button>
              </div>
              <ul className="text-sm space-y-1 mt-2 list-disc pl-4">
                {c.grey_facts.map(g => <li key={g.id}>{g.text}</li>)}
              </ul>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title="3. Thin coverage (< 2 green facts)"
        empty="All cells have at least 2 green facts."
        count={p.thinly_covered.length}
      >
        <table className="w-full text-sm">
          <thead className="text-[10px] font-mono uppercase text-ink-mute">
            <tr><th className="text-left py-1.5 pr-3">Cell</th>
                <th className="text-left py-1.5 pr-3">Layer → Subsection</th>
                <th className="text-right py-1.5 pr-3">green</th>
                <th></th></tr>
          </thead>
          <tbody>
            {p.thinly_covered.map(c => (
              <tr key={c.subsection_id} className="border-t border-ink-line">
                <td className="py-2 pr-3 font-mono text-xs">{c.subsection_id}</td>
                <td className="py-2 pr-3 text-sm">{c.layer_name} → {c.subsection_name}</td>
                <td className="py-2 pr-3 text-right font-mono text-sm">{c.n_green}</td>
                <td className="py-2 text-right">
                  <button onClick={() => onJumpToCell(c.subsection_id)}
                    className="text-xs px-2 py-1 hover:bg-slate-100 rounded text-blue-600">→ open</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

function Section({ title, count, empty, children }: {
  title: string; count: number; empty: string; children: React.ReactNode;
}) {
  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="text-xs text-ink-mute font-mono">{count}</span>
      </div>
      {count === 0 ? (
        <div className="text-xs text-ink-mute italic">{empty}</div>
      ) : children}
    </section>
  );
}
