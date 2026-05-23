import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type {
  Client, ClientMethodologyCell, MethodologyCell, TonePreset,
} from "../types";

interface Props {
  clientId: string;
}

type Mode = "global" | "client";

export default function MethodologyView({ clientId }: Props) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("global");

  const presets = useQuery({ queryKey: ["tone-presets"], queryFn: api.tonePresets });
  const client = useQuery<Client>({
    queryKey: ["client", clientId],
    queryFn: () => api.getClient(clientId),
  });
  const globalCells = useQuery({
    queryKey: ["methodology"],
    queryFn: api.methodology,
  });
  const clientCells = useQuery({
    queryKey: ["client-methodology", clientId],
    queryFn: () => api.clientMethodology(clientId),
  });

  return (
    <div className="p-5 max-w-4xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Methodology</h2>
        <div className="text-xs text-ink-mute mt-0.5">
          Описание ячейки = что в принципе сюда относится (общее для всех клиентов).{" "}
          Приписка «For this client» = что особенно важно для конкретной компании
          (добавляется к описанию в prompt). Тон = регистр формулировок (per-client).
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

      {/* Mode switcher */}
      <div className="flex items-center gap-1 border-b border-ink-line">
        <ModeTab active={mode === "global"} onClick={() => setMode("global")}
                 label="Global descriptions" hint="общие для всех клиентов" />
        <ModeTab active={mode === "client"} onClick={() => setMode("client")}
                 label={`For ${client.data?.name ?? "this client"}`}
                 hint="добавляется к global для этого клиента" />
      </div>

      {mode === "global" && (
        <GlobalCellsSection
          cells={globalCells.data ?? []}
          isLoading={globalCells.isLoading}
          onSave={async (sid, description) => {
            await api.updateMethodology(sid, description);
            qc.invalidateQueries({ queryKey: ["methodology"] });
            qc.invalidateQueries({ queryKey: ["client-methodology", clientId] });
          }}
        />
      )}

      {mode === "client" && (
        <ClientCellsSection
          cells={clientCells.data ?? []}
          isLoading={clientCells.isLoading}
          onSave={async (sid, note) => {
            await api.updateClientMethodology(clientId, sid, note);
            qc.invalidateQueries({ queryKey: ["client-methodology", clientId] });
          }}
        />
      )}
    </div>
  );
}

function ModeTab({ active, onClick, label, hint }: {
  active: boolean; onClick: () => void; label: string; hint: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm border-b-2 transition ${
        active ? "border-ink text-ink font-medium" : "border-transparent text-ink-mute hover:text-ink"
      }`}
    >
      {label}
      <span className="ml-2 text-[10px] text-ink-mute font-normal">— {hint}</span>
    </button>
  );
}

// ── Tone preset selector ──────────────────────────────────────────────────────

function TonePresetSection({ client, presets, isLoading, onSave }: {
  client?: Client;
  presets: TonePreset[];
  isLoading: boolean;
  onSave: (preset_id: string) => Promise<void>;
}) {
  const current = client?.tone_preset || "business";
  const [picked, setPicked] = useState<string | null>(null);
  const effective = picked ?? current;
  const dirty = picked != null && picked !== current;

  const saveMut = useMutation({
    mutationFn: async () => { if (picked) await onSave(picked); },
    onSuccess: () => setPicked(null),
  });

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-mute">
          Tone preset · per-client
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
                {isOn && (
                  <span className="text-[10px] text-ink-mute">
                    {picked === p.id && dirty ? "selected" : "current"}
                  </span>
                )}
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

// ── Global cells (shared across all clients) ─────────────────────────────────

function GlobalCellsSection({ cells, isLoading, onSave }: {
  cells: MethodologyCell[];
  isLoading: boolean;
  onSave: (sid: string, description: string) => Promise<void>;
}) {
  return (
    <CellsByLayer
      cells={cells}
      isLoading={isLoading}
      bannerColor="slate"
      bannerText="Эти описания общие для ВСЕХ клиентов. Меняй здесь только методологическую константу."
      getCurrentValue={(c) => c.description}
      onSave={onSave}
      placeholder="Что в принципе попадает в эту ячейку? Что НЕ попадает? (общее для всех клиентов)"
    />
  );
}

// ── Client-specific notes (additive on top of global) ────────────────────────

function ClientCellsSection({ cells, isLoading, onSave }: {
  cells: ClientMethodologyCell[];
  isLoading: boolean;
  onSave: (sid: string, note: string) => Promise<void>;
}) {
  return (
    <CellsByLayer
      cells={cells}
      isLoading={isLoading}
      bannerColor="amber"
      bannerText="Эти приписки относятся только к этому клиенту. Они добавляются к глобальному описанию в prompt как «For this client:» строка."
      getCurrentValue={(c) => (c as ClientMethodologyCell).client_note}
      getGlobal={(c) => (c as ClientMethodologyCell).description}
      onSave={onSave}
      placeholder="Что особенно важно в этой ячейке для этого клиента? Имена, числа, фокус. (опционально, может быть пусто)"
    />
  );
}

// ── Shared layered list ──────────────────────────────────────────────────────

function CellsByLayer({
  cells, isLoading, bannerColor, bannerText, getCurrentValue, getGlobal,
  onSave, placeholder,
}: {
  cells: (MethodologyCell | ClientMethodologyCell)[];
  isLoading: boolean;
  bannerColor: "slate" | "amber";
  bannerText: string;
  getCurrentValue: (c: MethodologyCell | ClientMethodologyCell) => string;
  getGlobal?: (c: MethodologyCell | ClientMethodologyCell) => string;
  onSave: (sid: string, value: string) => Promise<void>;
  placeholder: string;
}) {
  const grouped = new Map<number, {
    layerName: string;
    cells: (MethodologyCell | ClientMethodologyCell)[];
  }>();
  for (const c of cells) {
    const g = grouped.get(c.layer_id) ?? { layerName: c.layer_name, cells: [] };
    g.cells.push(c);
    grouped.set(c.layer_id, g);
  }
  const layerIds = Array.from(grouped.keys()).sort((a, b) => a - b);

  const bannerCls = bannerColor === "amber"
    ? "bg-amber-50 border-amber-300 text-amber-900"
    : "bg-slate-50 border-slate-300 text-slate-700";

  return (
    <section className="space-y-4">
      <div className={`text-xs rounded-lg border px-3 py-2 ${bannerCls}`}>
        {bannerText}
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
                <CellRow
                  key={c.subsection_id}
                  cell={c}
                  currentValue={getCurrentValue(c)}
                  globalText={getGlobal?.(c)}
                  onSave={onSave}
                  placeholder={placeholder}
                />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function CellRow({
  cell, currentValue, globalText, onSave, placeholder,
}: {
  cell: MethodologyCell | ClientMethodologyCell;
  currentValue: string;
  globalText?: string;
  onSave: (sid: string, value: string) => Promise<void>;
  placeholder: string;
}) {
  const [draft, setDraft] = useState(currentValue);
  const dirty = draft.trim() !== currentValue.trim();
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
      {globalText !== undefined && globalText.trim() && (
        <details className="mb-2 text-xs">
          <summary className="cursor-pointer text-ink-mute hover:text-ink">
            global description (inherited)
          </summary>
          <div className="mt-1 text-slate-600 border-l-2 border-slate-200 pl-2 whitespace-pre-wrap">
            {globalText}
          </div>
        </details>
      )}
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        placeholder={placeholder}
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
            onClick={() => setDraft(currentValue)}
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
