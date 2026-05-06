import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { cellModeStyles, modeOf } from "../lib/cellColor";
import type { CellSummary, Layer } from "../types";

interface Props {
  clientId: string;
  selectedSubsectionId?: string;
  onSelectCell: (sid: string) => void;
}

export default function MatrixGrid({ clientId, selectedSubsectionId, onSelectCell }: Props) {
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

  return (
    <div className="p-5 space-y-3">
      <div className="flex items-end justify-between mb-2">
        <h2 className="text-lg font-semibold">Narrative matrix</h2>
        <Legend />
      </div>

      <div className="space-y-1.5">
        {layers.data.map(L => (
          <div key={L.id} className="flex items-stretch gap-1.5">
            {/* Layer label */}
            <div className="w-56 shrink-0 px-3 py-2 bg-white rounded border border-ink-line">
              <div className="text-[10px] font-mono text-ink-mute">L{L.id}</div>
              <div className="text-xs font-semibold leading-tight">{L.name}</div>
              <div className="text-[10px] text-ink-mute mt-1 truncate" title={L.primary_channels.join(", ")}>
                {L.primary_channels.map(ch => ch.replace("_", " ")).join(" · ")}
              </div>
            </div>

            {/* Cells in this layer */}
            <div className="flex-1 grid gap-1.5"
                 style={{ gridTemplateColumns: `repeat(${L.subsections.length}, minmax(0, 1fr))` }}>
              {L.subsections.map(s => {
                const cell = cellBySid.get(s.id);
                if (!cell) return null;
                const mode = modeOf(cell);
                const style = cellModeStyles[mode];
                const selected = selectedSubsectionId === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => onSelectCell(s.id)}
                    className={`text-left p-2 rounded border transition relative
                      ${style.bg} ${style.border}
                      ${selected ? "ring-2 ring-blue-500 ring-offset-1" : "hover:ring-1 hover:ring-ink/20"}`}
                  >
                    <div className="text-[10px] font-mono text-ink-mute">{s.id}</div>
                    <div className={`text-xs font-medium leading-tight ${style.text}`}>{s.name}</div>
                    <div className="flex gap-1 mt-1.5 text-[10px] font-mono">
                      {cell.n_green > 0 && <span className="text-flag-green">●{cell.n_green}</span>}
                      {cell.n_red > 0   && <span className="text-flag-red">●{cell.n_red}</span>}
                      {cell.n_grey > 0  && <span className="text-flag-grey">●{cell.n_grey}</span>}
                      {cell.n_green + cell.n_red + cell.n_grey === 0 && (
                        <span className="text-slate-400">—</span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Legend() {
  const items: { mode: keyof typeof cellModeStyles; label: string }[] = [
    { mode: "green", label: "covered" },
    { mode: "red",   label: "concern" },
    { mode: "mixed", label: "mixed" },
    { mode: "grey",  label: "explicit gap" },
    { mode: "empty", label: "untouched" },
  ];
  return (
    <div className="flex gap-2 text-[10px] font-mono">
      {items.map(({ mode, label }) => (
        <div key={mode} className="flex items-center gap-1">
          <span className={`w-3 h-3 rounded-sm border ${cellModeStyles[mode].bg} ${cellModeStyles[mode].border}`} />
          <span className="text-ink-mute uppercase">{label}</span>
        </div>
      ))}
    </div>
  );
}
