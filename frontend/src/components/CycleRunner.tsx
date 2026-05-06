import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import type { Layer } from "../types";

interface Props {
  clientId: string;
  quarter: string;
  kind: "weekly" | "event" | "quarterly";
  onClose: () => void;
  onArtifactCreated: (artifactId: number) => void;
}

export default function CycleRunner({ clientId, quarter, kind, onClose, onArtifactCreated }: Props) {
  const qc = useQueryClient();
  const layers = useQuery<Layer[]>({ queryKey: ["layers"], queryFn: api.layers });

  // Weekly state
  const [weekLabel, setWeekLabel] = useState<string>(isoWeekLabel());
  const [maxFacts, setMaxFacts] = useState(3);

  // Event state
  const [eventText, setEventText] = useState("");
  const [landed, setLanded] = useState("8.2");

  // Quarterly state
  const [traversal, setTraversal] = useState<"inside_out" | "outside_in">("inside_out");
  const [factsPerSub, setFactsPerSub] = useState(2);

  const run = useMutation({
    mutationFn: async () => {
      if (kind === "weekly") {
        return api.runWeekly(clientId, { quarter, week_label: weekLabel, max_facts: maxFacts });
      } else if (kind === "event") {
        return api.runEvent(clientId, {
          event_text: eventText, landed_subsection_id: landed, quarter,
        });
      } else {
        return api.runQuarterly(clientId, {
          quarter, traversal, facts_per_subsection: factsPerSub,
        });
      }
    },
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["artifacts", clientId] });
      onArtifactCreated(a.id);
    },
  });

  return (
    <div className="fixed inset-0 z-40 bg-black/30 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl w-full max-w-md"
           onClick={e => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-ink-line flex items-center justify-between">
          <div>
            <div className="text-[10px] font-mono text-ink-mute uppercase">{kind} cycle</div>
            <h3 className="text-base font-semibold">
              {kind === "weekly" && "Weekly бриф"}
              {kind === "event" && "Event-реакция"}
              {kind === "quarterly" && "Квартальный досье"}
            </h3>
          </div>
          <button onClick={onClose} className="text-ink-mute hover:text-ink p-1">
            <svg width="20" height="20" viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15"
              stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none"/></svg>
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="text-xs text-ink-mute">
            client <span className="font-mono">{clientId}</span> · quarter <span className="font-mono">{quarter}</span>
          </div>

          {kind === "weekly" && (
            <>
              <Field label="Week label">
                <input value={weekLabel} onChange={e => setWeekLabel(e.target.value)}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 font-mono" />
              </Field>
              <Field label="Max facts in brief">
                <input type="number" min={1} max={10} value={maxFacts}
                  onChange={e => setMaxFacts(Number(e.target.value))}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 font-mono" />
              </Field>
            </>
          )}

          {kind === "event" && (
            <>
              <Field label="Event text">
                <textarea value={eventText} onChange={e => setEventText(e.target.value)}
                  rows={3}
                  placeholder="ФРС снизила ставку на 50бп; вторичный рынок +22% w/w"
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5" />
              </Field>
              <Field label="Lands in subsection">
                <select value={landed} onChange={e => setLanded(e.target.value)}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5">
                  {layers.data?.flatMap(L =>
                    L.subsections.map(s => (
                      <option key={s.id} value={s.id}>{s.id} · L{L.id} {L.name} → {s.name}</option>
                    ))
                  )}
                </select>
              </Field>
            </>
          )}

          {kind === "quarterly" && (
            <>
              <Field label="Traversal">
                <select value={traversal}
                  onChange={e => setTraversal(e.target.value as "inside_out" | "outside_in")}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5">
                  <option value="inside_out">inside-out (L1 → L8)</option>
                  <option value="outside_in">outside-in (L8 → L1)</option>
                </select>
              </Field>
              <Field label="Facts per subsection">
                <input type="number" min={1} max={5} value={factsPerSub}
                  onChange={e => setFactsPerSub(Number(e.target.value))}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 font-mono" />
              </Field>
            </>
          )}

          {run.isError && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">
              {(run.error as Error).message}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-ink-line bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose}
            className="text-sm px-3 py-1.5 hover:bg-slate-200 rounded text-ink-mute">Cancel</button>
          <button
            onClick={() => run.mutate()}
            disabled={run.isPending || (kind === "event" && !eventText.trim())}
            className="text-sm px-4 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
          >
            {run.isPending ? "Running…" : "Run"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs font-medium text-ink-mute uppercase tracking-wide mb-1">{label}</div>
      {children}
    </label>
  );
}

function isoWeekLabel(d = new Date()): string {
  // Approximate ISO week label
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}
