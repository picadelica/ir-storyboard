import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Layer, Track } from "../types";

interface Props {
  clientId: string;
  quarter: string;
  layers?: Layer[];
}

export default function PlanView({ clientId, quarter, layers }: Props) {
  const qc = useQueryClient();
  const tracks = useQuery({
    queryKey: ["tracks", clientId, quarter],
    queryFn: () => api.tracks(clientId, quarter),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="p-5 max-w-4xl space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Plan · {quarter}</h2>
        <div className="text-xs text-ink-mute mt-0.5">
          Narrative tracks определяют, на каких слоях/ячейках фокусируется
          weekly / event / quarterly cycle. Без активного трека Weekly бриф
          не отрендерится — cycle track-ориентирован by design.
        </div>
      </div>

      {tracks.isLoading && <div className="text-sm text-ink-mute">Loading…</div>}

      {tracks.data && tracks.data.length === 0 && !showForm && (
        <div className="border border-amber-300 bg-amber-50 rounded-lg p-4 text-sm text-amber-900">
          <div className="font-medium mb-1">No tracks for {quarter}.</div>
          <div className="text-xs">
            Создай хотя бы один трек, чтобы Weekly cycle мог работать.
          </div>
        </div>
      )}

      {tracks.data && tracks.data.length > 0 && (
        <div className="space-y-3">
          {tracks.data
            .slice()
            .sort((a, b) => a.priority - b.priority)
            .map((t) => (
              <TrackCard key={t.id} track={t} layers={layers} />
            ))}
        </div>
      )}

      {!showForm && (
        <button
          onClick={() => setShowForm(true)}
          className="text-sm px-4 py-2 bg-ink text-white rounded hover:bg-ink/90"
        >
          + New track
        </button>
      )}

      {showForm && (
        <NewTrackForm
          layers={layers ?? []}
          onCancel={() => setShowForm(false)}
          onSubmit={async (body) => {
            await api.addTrack(clientId, quarter, body);
            qc.invalidateQueries({ queryKey: ["tracks", clientId, quarter] });
            qc.invalidateQueries({ queryKey: ["client-summary", clientId] });
            setShowForm(false);
          }}
        />
      )}
    </div>
  );
}

function TrackCard({ track, layers }: { track: Track; layers?: Layer[] }) {
  const layerName = (id: number) =>
    layers?.find((l) => l.id === id)?.name ?? `L${id}`;
  const subName = (sid: string) => {
    for (const l of layers ?? [])
      for (const s of l.subsections) if (s.id === sid) return s.name;
    return sid;
  };

  return (
    <div className="border border-ink-line rounded-lg p-4 bg-white">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-medium text-sm">{track.name}</div>
        <div className="text-[10px] font-mono text-ink-mute uppercase">
          priority {track.priority}
        </div>
      </div>
      {track.angle && (
        <div className="text-xs text-slate-600 mt-1 italic">{track.angle}</div>
      )}
      {track.target_layer_ids.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {track.target_layer_ids.map((lid) => (
            <span
              key={lid}
              className="text-[11px] px-2 py-0.5 bg-slate-100 border border-slate-200 rounded font-mono"
            >
              L{lid} · {layerName(lid)}
            </span>
          ))}
        </div>
      )}
      {track.target_subsection_ids.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {track.target_subsection_ids.map((sid) => (
            <span
              key={sid}
              className="text-[11px] px-2 py-0.5 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded font-mono"
            >
              {sid} · {subName(sid)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function NewTrackForm({
  layers,
  onCancel,
  onSubmit,
}: {
  layers: Layer[];
  onCancel: () => void;
  onSubmit: (body: {
    name: string;
    angle?: string;
    target_layer_ids: number[];
    target_subsection_ids: string[];
    priority?: number;
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [angle, setAngle] = useState("");
  const [priority, setPriority] = useState(1);
  const [layerIds, setLayerIds] = useState<Set<number>>(new Set());
  const [subIds, setSubIds] = useState<Set<string>>(new Set());
  const [granular, setGranular] = useState(false);

  const submit = useMutation({
    mutationFn: () =>
      onSubmit({
        name: name.trim(),
        angle: angle.trim() || undefined,
        target_layer_ids: granular ? [] : Array.from(layerIds),
        target_subsection_ids: granular ? Array.from(subIds) : [],
        priority,
      }),
  });

  const canSubmit =
    name.trim().length > 0 &&
    (granular ? subIds.size > 0 : layerIds.size > 0) &&
    !submit.isPending;

  const toggleLayer = (id: number) => {
    const next = new Set(layerIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setLayerIds(next);
  };
  const toggleSub = (sid: string) => {
    const next = new Set(subIds);
    next.has(sid) ? next.delete(sid) : next.add(sid);
    setSubIds(next);
  };

  return (
    <div className="border border-ink-line rounded-lg p-4 bg-white space-y-4">
      <div className="text-sm font-semibold">New track</div>

      <Field label="Name" hint="короткое имя трека, например «Founder origin story»">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full text-sm border border-slate-300 rounded px-2 py-1.5"
          placeholder="Founder origin story"
        />
      </Field>

      <Field
        label="Angle"
        hint="одно предложение про cause → effect → so what (опционально, попадает в prompt)"
      >
        <textarea
          value={angle}
          onChange={(e) => setAngle(e.target.value)}
          rows={2}
          className="w-full text-sm border border-slate-300 rounded px-2 py-1.5 resize-y"
          placeholder="Как личная история фаундера объясняет нынешнюю продуктовую стратегию"
        />
      </Field>

      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <div className="text-xs font-medium text-ink-mute uppercase">
            Target {granular ? "subsections" : "layers"}
          </div>
          <button
            type="button"
            onClick={() => setGranular(!granular)}
            className="text-[11px] text-ink-mute hover:text-ink underline"
          >
            {granular ? "→ pick whole layers" : "→ pick individual subsections"}
          </button>
        </div>

        {!granular && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
            {layers.map((l) => {
              const on = layerIds.has(l.id);
              return (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => toggleLayer(l.id)}
                  className={`text-left text-xs px-2.5 py-1.5 border rounded transition ${
                    on
                      ? "border-ink bg-ink/5 ring-1 ring-ink"
                      : "border-ink-line bg-white hover:border-slate-400"
                  }`}
                >
                  <span className="font-mono text-[10px] text-ink-mute mr-1">
                    L{l.id}
                  </span>
                  {l.name}
                </button>
              );
            })}
          </div>
        )}

        {granular && (
          <div className="space-y-2">
            {layers.map((l) => (
              <div key={l.id} className="space-y-1">
                <div className="text-[11px] font-medium text-ink-mute">
                  L{l.id}. {l.name}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-1.5">
                  {l.subsections.map((s) => {
                    const on = subIds.has(s.id);
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => toggleSub(s.id)}
                        className={`text-left text-xs px-2 py-1 border rounded transition ${
                          on
                            ? "border-ink bg-ink/5 ring-1 ring-ink"
                            : "border-ink-line bg-white hover:border-slate-400"
                        }`}
                      >
                        <span className="font-mono text-[10px] text-ink-mute mr-1">
                          {s.id}
                        </span>
                        {s.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Field label="Priority" hint="1 = самый важный; weekly использует трек с highest priority">
        <input
          type="number"
          min={1}
          max={99}
          value={priority}
          onChange={(e) => setPriority(Number(e.target.value) || 1)}
          className="w-24 text-sm border border-slate-300 rounded px-2 py-1.5 font-mono"
        />
      </Field>

      {submit.isError && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">
          {(submit.error as Error).message}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2 border-t border-ink-line">
        <button
          onClick={onCancel}
          className="text-sm px-3 py-1.5 text-ink-mute hover:bg-slate-100 rounded"
        >
          Cancel
        </button>
        <button
          onClick={() => submit.mutate()}
          disabled={!canSubmit}
          className={`text-sm px-4 py-1.5 rounded font-medium transition ${
            canSubmit
              ? "bg-ink text-white hover:bg-ink/90"
              : "bg-slate-200 text-slate-400 cursor-not-allowed"
          }`}
        >
          {submit.isPending ? "Creating…" : "Create track"}
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-ink-mute uppercase tracking-wide">
        {label}
      </div>
      {hint && <div className="text-[11px] text-ink-mute">{hint}</div>}
      {children}
    </div>
  );
}
