import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Track } from "../types";

interface Props {
  clientId?: string;
  quarter: string;
  onQuarterChange: (q: string) => void;
  onRunCycle: (kind: "weekly" | "event" | "quarterly") => void;
}

export default function Sidebar({ clientId, quarter, onQuarterChange, onRunCycle }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { tab } = useParams();

  const clients = useQuery({ queryKey: ["clients"], queryFn: api.listClients });
  const tracks = useQuery({
    queryKey: ["tracks", clientId, quarter],
    queryFn: () => api.tracks(clientId!, quarter),
    enabled: !!clientId,
  });

  const seedAcc = useMutation({
    mutationFn: api.seedAccumulator,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      nav("/clients/accumulator");
    },
  });

  return (
    <aside className="w-72 shrink-0 border-r border-ink-line bg-white flex flex-col">
      <div className="px-4 py-4 border-b border-ink-line">
        <div className="text-base font-semibold tracking-tight">IR Storyboard</div>
        <div className="text-xs text-ink-mute mt-0.5">narrative matrix · cycles · outputs</div>
      </div>

      {/* Clients */}
      <div className="px-3 py-3">
        <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide mb-1.5 px-1">Clients</div>
        {clients.isLoading && <div className="text-xs text-ink-mute px-1 py-1">Loading…</div>}
        {clients.data && clients.data.length === 0 && (
          <button
            onClick={() => seedAcc.mutate()}
            className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-slate-100 text-blue-600"
          >+ Загрузить пилот (Accumulator)</button>
        )}
        <ul className="space-y-0.5">
          {clients.data?.map(c => (
            <li key={c.id}>
              <Link
                to={`/clients/${c.id}/${tab ?? "matrix"}`}
                className={`flex items-center justify-between px-2 py-1.5 rounded text-sm
                  ${clientId === c.id ? "bg-slate-100 font-medium" : "hover:bg-slate-50"}`}
              >
                <span>{c.name}</span>
                <span className="text-[10px] text-ink-mute uppercase truncate ml-2">{c.sector?.split("/")[0]}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>

      {clientId && (
        <>
          <div className="px-4 py-3 border-t border-ink-line">
            <label className="text-xs font-semibold uppercase text-ink-mute tracking-wide">Quarter</label>
            <input
              value={quarter}
              onChange={e => onQuarterChange(e.target.value)}
              className="mt-1 w-full text-sm border border-ink-line rounded px-2 py-1 font-mono"
              placeholder="2026Q2"
            />
          </div>

          <div className="px-3 py-3 border-t border-ink-line">
            <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide mb-1.5 px-1">
              Active narrative tracks
            </div>
            {tracks.isLoading && <div className="text-xs text-ink-mute px-1">Loading…</div>}
            {tracks.data && tracks.data.length === 0 && (
              <div className="text-xs text-ink-mute px-1">No tracks for {quarter}.</div>
            )}
            <ul className="space-y-1.5">
              {tracks.data?.map((t: Track) => (
                <li key={t.id} className="px-2 py-1.5 bg-slate-50 rounded border border-ink-line/60">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className="inline-block text-[10px] font-mono px-1.5 py-0.5 bg-slate-200 rounded">P{t.priority}</span>
                    <span className="text-xs font-medium leading-snug">{t.name}</span>
                  </div>
                  {t.angle && <div className="text-[11px] text-ink-mute leading-snug">{t.angle}</div>}
                  <div className="text-[10px] text-ink-mute font-mono mt-1">L{t.target_layer_ids.join(",")}</div>
                </li>
              ))}
            </ul>
          </div>

          <div className="px-3 py-3 border-t border-ink-line mt-auto bg-slate-50">
            <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide mb-2 px-1">Run cycle</div>
            <div className="grid grid-cols-1 gap-1.5">
              <button
                onClick={() => onRunCycle("weekly")}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
              >Weekly бриф</button>
              <button
                onClick={() => onRunCycle("event")}
                className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded hover:bg-amber-700"
              >Event-реакция</button>
              <button
                onClick={() => onRunCycle("quarterly")}
                className="text-xs px-3 py-1.5 bg-emerald-700 text-white rounded hover:bg-emerald-800"
              >Квартальный досье</button>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
