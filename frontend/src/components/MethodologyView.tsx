import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import type {
  Client, ClientMethodologyCell, MethodologyCell, TonePreset,
  MethodologyMove, ReclassifyResult, Layer,
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
        <h2 className="text-lg font-semibold">Методология</h2>
        <div className="text-xs text-ink-mute mt-0.5">
          Описание ячейки = что в принципе сюда относится (общее для всех клиентов).{" "}
          Приписка «For this client» = что особенно важно для конкретной компании
          (добавляется к описанию в prompt). Тон = регистр формулировок (per-client).
        </div>
      </div>

      <ReapplyMethodologySection
        clientId={clientId}
        clientName={client.data?.name ?? "клиента"}
      />

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
      {isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
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
    const g = grouped.get(c.layer_id) ?? { layerName: layerNameRu(c.layer_id, c.layer_name), cells: [] };
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
      {isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
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
        <span className="text-sm font-medium">{subsectionNameRu(cell.subsection_id, cell.subsection_name)}</span>
        {dirty && <span className="text-[10px] text-amber-600 ml-auto">не сохранено</span>}
      </div>
      {globalText !== undefined && globalText.trim() && (
        <details className="mb-2 text-xs">
          <summary className="cursor-pointer text-ink-mute hover:text-ink">
            общее описание (унаследовано)
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
          {saveMut.isPending ? "Сохраняю…" : "Сохранить"}
        </button>
        {dirty && (
          <button
            onClick={() => setDraft(currentValue)}
            className="text-xs px-3 py-1 border border-slate-300 text-slate-600 rounded hover:bg-slate-100"
          >
            Откатить
          </button>
        )}
        {saveMut.isError && (
          <span className="text-xs text-red-600">{String(saveMut.error)}</span>
        )}
        {saveMut.isSuccess && !dirty && (
          <span className="text-xs text-emerald-600">сохранено</span>
        )}
      </div>
    </div>
  );
}

// ── Переосмысление раскладки при смене методологии ───────────────────────────

function ReapplyMethodologySection({ clientId, clientName }: {
  clientId: string; clientName: string;
}) {
  const qc = useQueryClient();
  const [preview, setPreview] = useState<ReclassifyResult | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // ручное переопределение целевого раздела для переезда (по умолчанию — предложение LLM)
  const [overrides, setOverrides] = useState<Record<number, string>>({});
  const layers = useQuery({ queryKey: ["layers"], queryFn: api.layers });
  const targetOf = (m: MethodologyMove) => overrides[m.fact_id] ?? m.to_sid;

  const runMut = useMutation({
    mutationFn: () => api.reclassifyMethodology(clientId),
    onSuccess: (res) => {
      setPreview(res);
      setSelected(new Set(res.moves.map((m) => m.fact_id)));  // по умолчанию все выбраны
      setOverrides({});
    },
  });

  const applyMut = useMutation({
    mutationFn: () => {
      const moves = (preview?.moves ?? [])
        .filter((m) => selected.has(m.fact_id) && targetOf(m) !== m.from_sid)
        .map((m) => ({ fact_id: m.fact_id, to_sid: targetOf(m) }));
      return api.applyMethodologyMoves(clientId, moves);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "facts" });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
      qc.invalidateQueries({ queryKey: ["review-queue", clientId] });
      setPreview(null);
    },
  });

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });

  return (
    <section className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Переосмысление раскладки</h3>
          <div className="text-xs text-ink-mute mt-0.5">
            Изменили методологию выше? Пересчитайте раскладку активных фактов «{clientName}»
            по новым описаниям — увидите, какие карточки переезжают и куда, и подтвердите.
          </div>
        </div>
        <button
          onClick={() => runMut.mutate()}
          disabled={runMut.isPending}
          className="shrink-0 text-xs px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {runMut.isPending ? "Считаю переезды…" : "Применить новую методологию"}
        </button>
      </div>
      {runMut.isError && (
        <div className="text-xs text-red-600">{String(runMut.error)}</div>
      )}
      {preview && (
        <MovesPreviewModal
          preview={preview}
          selected={selected}
          onToggle={toggle}
          onSelectAll={() => setSelected(new Set(preview.moves.map((m) => m.fact_id)))}
          onSelectNone={() => setSelected(new Set())}
          onClose={() => setPreview(null)}
          onApply={() => applyMut.mutate()}
          applying={applyMut.isPending}
          error={applyMut.isError ? String(applyMut.error) : null}
          layers={layers.data ?? []}
          targetOf={targetOf}
          onChangeTarget={(id, sid) => setOverrides((o) => ({ ...o, [id]: sid }))}
        />
      )}
    </section>
  );
}

function MovesPreviewModal({
  preview, selected, onToggle, onSelectAll, onSelectNone, onClose, onApply, applying, error,
  layers, targetOf, onChangeTarget,
}: {
  preview: ReclassifyResult;
  selected: Set<number>;
  onToggle: (id: number) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onClose: () => void;
  onApply: () => void;
  applying: boolean;
  error: string | null;
  layers: Layer[];
  targetOf: (m: MethodologyMove) => string;
  onChangeTarget: (id: number, sid: string) => void;
}) {
  const { moves, total } = preview;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[85vh] flex flex-col"
           onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-ink-line">
          <h3 className="text-base font-semibold">Переезды при новой методологии</h3>
          <div className="text-xs text-ink-mute mt-0.5">
            Из {total} активных фактов переезжает {moves.length}. Отметьте, какие применить.
          </div>
        </div>

        {moves.length === 0 ? (
          <div className="px-5 py-8 text-sm text-ink-mute text-center">
            Ничего не переезжает — раскладка уже соответствует текущей методологии.
          </div>
        ) : (
          <>
            <div className="px-5 py-2 border-b border-ink-line flex items-center gap-3 text-xs">
              <span className="text-ink-mute">Выбрано {selected.size} из {moves.length}</span>
              <button onClick={onSelectAll} className="text-indigo-600 hover:underline">все</button>
              <button onClick={onSelectNone} className="text-indigo-600 hover:underline">ничего</button>
            </div>
            <div className="overflow-y-auto flex-1 divide-y divide-ink-line">
              {moves.map((m) => (
                <MoveRow key={m.fact_id} move={m}
                         checked={selected.has(m.fact_id)}
                         onToggle={() => onToggle(m.fact_id)}
                         layers={layers}
                         value={targetOf(m)}
                         onChangeTarget={(sid) => onChangeTarget(m.fact_id, sid)} />
              ))}
            </div>
          </>
        )}

        <div className="px-5 py-3 border-t border-ink-line flex items-center justify-between gap-3">
          {error && <span className="text-xs text-red-600 truncate">{error}</span>}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onClose}
                    className="text-xs px-3 py-1.5 border border-slate-300 text-slate-600 rounded hover:bg-slate-100">
              Отмена
            </button>
            <button onClick={onApply}
                    disabled={applying || selected.size === 0}
                    className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-ink/90 disabled:opacity-50">
              {applying ? "Применяю…" : `Применить выбранные (${selected.size})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MoveRow({ move, checked, onToggle, layers, value, onChangeTarget }: {
  move: MethodologyMove; checked: boolean; onToggle: () => void;
  layers: Layer[]; value: string; onChangeTarget: (sid: string) => void;
}) {
  const overridden = value !== move.to_sid;
  return (
    <div className="flex items-start gap-3 px-5 py-2.5 hover:bg-slate-50">
      <input type="checkbox" checked={checked} onChange={onToggle} className="mt-1 cursor-pointer" />
      <div className="min-w-0 flex-1">
        <div className="text-sm">
          {move.title
            ? <span className="font-medium">{move.title}</span>
            : <span className="text-ink">{move.text}</span>}
        </div>
        {move.title && (
          <div className="text-xs text-ink-mute truncate">{move.text}</div>
        )}
        <div className="mt-1 flex items-center gap-1.5 text-xs">
          <span className="font-mono px-1 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">
            {move.from_sid}
          </span>
          <span className="text-ink-mute">→</span>
          <select
            value={value}
            onChange={(e) => onChangeTarget(e.target.value)}
            className={`font-mono text-xs rounded border px-1 py-0.5 cursor-pointer ${
              overridden
                ? "bg-amber-100 border-amber-300 text-amber-800"
                : "bg-emerald-100 border-emerald-200 text-emerald-700"
            }`}
          >
            {layers.map((l) => (
              <optgroup key={l.id} label={`${l.id}. ${layerNameRu(l.id, l.name)}`}>
                {l.subsections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id} · {subsectionNameRu(s.id, s.name)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {overridden && <span className="text-amber-700">(вручную)</span>}
          {move.rationale && !overridden && (
            <span className="text-ink-mute italic truncate">· {move.rationale}</span>
          )}
        </div>
      </div>
    </div>
  );
}
