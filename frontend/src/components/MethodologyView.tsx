import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Client, MethodologyCell, TonePreset } from "../types";

interface Props {
  clientId: string;
}

export default function MethodologyView({ clientId }: Props) {
  const qc = useQueryClient();
  const cells = useQuery({ queryKey: ["methodology"], queryFn: api.methodology });
  const presets = useQuery({ queryKey: ["tone-presets"], queryFn: api.tonePresets });
  const client = useQuery<Client>({
    queryKey: ["client", clientId],
    queryFn: () => api.getClient(clientId),
  });

  return (
    <div className="p-5 max-w-4xl space-y-8">
      <div>
        <h2 className="text-lg font-semibold">Methodology</h2>
        <div className="text-xs text-ink-mute mt-0.5">
          Описания ячеек и тон формулировок подмешиваются в каждый LLM-промпт.
          Описания глобальные (общие для всех клиентов); тон — per-client.
        </div>
      </div>

      <TonePresetSection
        client={client.data}
        presets={presets.data ?? []}
        isLoading={client.isLoading || presets.isLoading}
        onSave={async (preset_id) => {
          if (!client.data) return;
          await api.upsertClient({ ...client.data, tone_preset: preset_id });
          qc.invalidateQueries({ queryKey: ["client", clientId] });
          qc.invalidateQueries({ queryKey: ["clients"] });
        }}
      />

      <CellsSection
        cells={cells.data ?? []}
        isLoading={cells.isLoading}
        onSave={async (sid, description) => {
          await api.updateMethodology(sid, description);
          qc.invalidateQueries({ queryKey: ["methodology"] });
        }}
      />
    </div>
  );
}

// ── Tone preset selector ──────────────────────────────────────────────────────

interface TonePresetSectionProps {
  client?: Client;
  presets: TonePreset[];
  isLoading: boolean;
  onSave: (preset_id: string) => Promise<void>;
}

function TonePresetSection({ client, presets, isLoading, onSave }: TonePresetSectionProps) {
  const current = client?.tone_preset || "business";
  const [picked, setPicked] = useState<string | null>(null);
  const effective = picked ?? current;
  const dirty = picked != null && picked !== current;

  const saveMut = useMutation({
    mutationFn: async () => {
      if (picked) await onSave(picked);
    },
    onSuccess: () => setPicked(null),
  });

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-mute">
          Tone preset (per-client)
        </h3>
        {dirty && (
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="text-xs px-3 py-1 bg-ink text-white rounded hover:bg-ink/90 disabled:opacity-50"
          >
            {saveMut.isPending ? "Saving…" : "Save tone"}
          </button>
        )}
      </div>
      {isLoading && <div className="text-sm text-ink-mute">Loading…</div>}
      {!isLoading && presets.length === 0 && (
        <div className="text-sm text-ink-mute">No presets available.</div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {presets.map((p) => {
          const isOn = effective === p.id;
          return (
            <button
              key={p.id}
              onClick={() => setPicked(p.id)}
              className={`text-left border rounded-lg p-3 transition ${
                isOn
                  ? "border-ink bg-ink/5 ring-1 ring-ink"
                  : "border-ink-line bg-white hover:border-slate-400"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className="text-sm font-semibold">{p.label}</div>
                {isOn && <span className="text-[10px] text-ink-mute">
                  {picked === p.id && dirty ? "selected" : "current"}
                </span>}
              </div>
              <div className="text-xs text-ink-mute mt-1">{p.description}</div>
              <div className="text-xs text-slate-600 italic mt-2 border-l-2 border-slate-200 pl-2">
                {p.sample}
              </div>
            </button>
          );
        })}
      </div>
      {saveMut.isError && (
        <div className="text-xs text-red-600">{String(saveMut.error)}</div>
      )}
    </section>
  );
}

// ── Cells (24 subsections) ───────────────────────────────────────────────────

interface CellsSectionProps {
  cells: MethodologyCell[];
  isLoading: boolean;
  onSave: (sid: string, description: string) => Promise<void>;
}

function CellsSection({ cells, isLoading, onSave }: CellsSectionProps) {
  // Group by layer
  const grouped = new Map<number, { layerName: string; cells: MethodologyCell[] }>();
  for (const c of cells) {
    const g = grouped.get(c.layer_id) ?? { layerName: c.layer_name, cells: [] };
    g.cells.push(c);
    grouped.set(c.layer_id, g);
  }
  const layerIds = Array.from(grouped.keys()).sort((a, b) => a - b);

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-mute">
          Cell descriptions ({cells.length})
        </h3>
        <div className="text-[10px] text-ink-mute">
          Описания глобальные для всех клиентов
        </div>
      </div>
      {isLoading && <div className="text-sm text-ink-mute">Loading…</div>}
      {layerIds.map((lid) => {
        const g = grouped.get(lid)!;
        return (
          <div key={lid} className="space-y-2">
            <div className="text-xs font-medium text-ink-mute">
              L{lid}. {g.layerName}
            </div>
            <div className="space-y-2">
              {g.cells.map((c) => (
                <CellRow key={c.subsection_id} cell={c} onSave={onSave} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

interface CellRowProps {
  cell: MethodologyCell;
  onSave: (sid: string, description: string) => Promise<void>;
}

function CellRow({ cell, onSave }: CellRowProps) {
  const [draft, setDraft] = useState(cell.description);
  const dirty = draft.trim() !== cell.description.trim();
  const saveMut = useMutation({
    mutationFn: () => onSave(cell.subsection_id, draft.trim()),
  });

  return (
    <div className="border border-ink-line rounded-lg p-3 bg-white">
      <div className="flex items-baseline gap-2 mb-2">
        <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">
          {cell.subsection_id}
        </span>
        <span className="text-sm font-medium">{cell.subsection_name}</span>
        {dirty && <span className="text-[10px] text-amber-600 ml-auto">unsaved</span>}
      </div>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        placeholder="Что именно искать в этой ячейке? Что НЕ относится? Примеры формулировок…"
        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ink resize-y"
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={() => saveMut.mutate()}
          disabled={!dirty || saveMut.isPending}
          className={`text-xs px-3 py-1 rounded font-medium transition ${
            !dirty || saveMut.isPending
              ? "bg-slate-200 text-slate-400 cursor-not-allowed"
              : "bg-ink text-white hover:bg-ink/90"
          }`}
        >
          {saveMut.isPending ? "Saving…" : "Save"}
        </button>
        {dirty && (
          <button
            onClick={() => setDraft(cell.description)}
            className="text-xs px-3 py-1 border border-slate-300 text-slate-600 rounded hover:bg-slate-100"
          >
            Revert
          </button>
        )}
        {saveMut.isError && (
          <span className="text-xs text-red-600">{String(saveMut.error)}</span>
        )}
        {saveMut.isSuccess && !dirty && (
          <span className="text-xs text-emerald-600">saved</span>
        )}
      </div>
    </div>
  );
}
