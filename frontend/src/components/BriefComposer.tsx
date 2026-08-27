import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { layerNameRu } from "../lib/matrixLabels";
import type { BriefComposeResult, BriefTemplate, Layer } from "../types";

const FLAGS: { id: string; label: string; dot: string }[] = [
  { id: "green", label: "covered", dot: "bg-flag-green" },
  { id: "grey", label: "gaps", dot: "bg-flag-grey" },
  { id: "red", label: "concern", dot: "bg-flag-red" },
];

export default function BriefComposer({ clientId, layers }: { clientId: string; layers?: Layer[] }) {
  const templates = useQuery({ queryKey: ["brief-templates"], queryFn: api.briefTemplates });
  const [tplId, setTplId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [flags, setFlags] = useState<Set<string>>(new Set(["green", "grey"]));
  const [layerIds, setLayerIds] = useState<Set<number>>(new Set());
  const [format, setFormat] = useState<"md" | "json">("md");
  const [editing, setEditing] = useState<BriefTemplate | "new" | null>(null);
  const [result, setResult] = useState<BriefComposeResult | null>(null);
  const [copied, setCopied] = useState(false);

  const effTplId = tplId ?? templates.data?.[0]?.id ?? null;

  const composeMut = useMutation({
    mutationFn: () => api.composeBrief(clientId, {
      template_id: effTplId!,
      analyst_prompt: prompt,
      flags: flags.size ? [...flags] : null,
      layer_ids: layerIds.size ? [...layerIds] : null,
    }),
    onSuccess: setResult,
  });

  const toggleFlag = (v: string) => {
    const n = new Set(flags); n.has(v) ? n.delete(v) : n.add(v); setFlags(n);
  };
  const toggleLayer = (v: number) => {
    const n = new Set(layerIds); n.has(v) ? n.delete(v) : n.add(v); setLayerIds(n);
  };

  const output = result ? (format === "md" ? result.md : JSON.stringify(result.json_bundle, null, 2)) : "";

  const copy = async () => {
    try { await navigator.clipboard.writeText(output); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  const download = () => {
    const blob = new Blob([output], { type: format === "md" ? "text/markdown" : "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `brief-${clientId}.${format}`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const btn = "text-xs px-3 py-1.5 rounded-lg border border-ink-line text-ink hover:bg-ink/[0.04] disabled:opacity-50 transition";

  return (
    <div className="p-5 flex gap-5">
      {/* config */}
      <div className="w-[380px] shrink-0 space-y-5">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-ink-mute">Шаблон материала</label>
            <div className="flex gap-2 text-[11px]">
              {effTplId && (
                <button className="text-ink-mute hover:text-ink"
                  onClick={() => setEditing(templates.data!.find(t => t.id === effTplId)!)}>править</button>
              )}
              <button className="text-ink-mute hover:text-ink" onClick={() => setEditing("new")}>+ новый</button>
            </div>
          </div>
          <select
            value={effTplId ?? ""}
            onChange={e => setTplId(Number(e.target.value))}
            className="w-full text-sm border border-ink-line rounded-lg px-2 py-2 bg-white"
          >
            {templates.data?.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>

        <div>
          <label className="text-xs font-medium text-ink-mute">Фактология — флаги</label>
          <div className="flex gap-2 mt-1.5">
            {FLAGS.map(f => (
              <button key={f.id} onClick={() => toggleFlag(f.id)}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition
                  ${flags.has(f.id) ? "border-ink bg-ink/[0.05] text-ink" : "border-ink-line text-ink-mute"}`}>
                <span className={`w-2 h-2 rounded-full ${f.dot}`} />{f.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-ink-mute">Слои (пусто = все)</label>
          <div className="grid grid-cols-2 gap-1.5 mt-1.5">
            {(layers ?? []).map(L => (
              <button key={L.id} onClick={() => toggleLayer(L.id)}
                className={`flex items-center gap-1.5 text-[11px] px-2 py-1.5 rounded-lg border text-left transition
                  ${layerIds.has(L.id) ? "border-ink bg-ink/[0.05] text-ink" : "border-ink-line text-ink-mute"}`}>
                <span className="font-mono tabular-nums">{L.id}</span>
                <span className="truncate">{layerNameRu(L.id, L.name)}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-ink-mute">Постановка аналитика</label>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={5}
            placeholder="Например: 3-мин ролик про компанию для crypto-аудитории, дерзкий тон, фокус на фаундерах и продукте."
            className="w-full mt-1.5 text-sm border border-ink-line rounded-lg px-3 py-2 resize-none" />
        </div>

        <button onClick={() => composeMut.mutate()} disabled={!effTplId || composeMut.isPending}
          className="w-full py-2.5 rounded-xl bg-ink text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition">
          {composeMut.isPending ? "Собираю…" : "Собрать бриф"}
        </button>
      </div>

      {/* output */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center rounded-lg border border-ink-line overflow-hidden text-xs">
            <button onClick={() => setFormat("md")}
              className={`px-3 py-1.5 ${format === "md" ? "bg-ink text-white" : "text-ink-mute"}`}>MD</button>
            <button onClick={() => setFormat("json")}
              className={`px-3 py-1.5 ${format === "json" ? "bg-ink text-white" : "text-ink-mute"}`}>JSON</button>
          </div>
          <div className="flex items-center gap-2">
            {result && <span className="text-[11px] text-ink-mute tabular-nums">{result.fact_count} фактов</span>}
            <button onClick={copy} disabled={!output} className={btn}>{copied ? "Скопировано ✓" : "Копировать"}</button>
            <button onClick={download} disabled={!output} className={btn}>Скачать</button>
          </div>
        </div>
        <pre className="text-xs font-mono leading-5 whitespace-pre-wrap break-words bg-white border border-ink-line rounded-xl p-4 overflow-auto"
          style={{ maxHeight: "calc(100vh - 200px)" }}>
          {output || "Настрой слева и нажми «Собрать бриф» — здесь появится готовый MD/JSON для вставки в LLM."}
        </pre>
      </div>

      {editing && (
        <TemplateEditor
          template={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(t) => { setTplId(t.id); setEditing(null); }}
        />
      )}
    </div>
  );
}

function TemplateEditor({ template, onClose, onSaved }:
  { template: BriefTemplate | null; onClose: () => void; onSaved: (t: BriefTemplate) => void }) {
  const qc = useQueryClient();
  const isEdit = !!template;
  const [name, setName] = useState(template?.name ?? "");
  const [materialType, setMaterialType] = useState(template?.material_type ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [error, setError] = useState("");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["brief-templates"] });

  const saveMut = useMutation({
    mutationFn: () => {
      if (!name.trim()) throw new Error("Имя обязательно");
      const payload = { name, material_type: materialType, body };
      return isEdit ? api.updateBriefTemplate(template!.id, payload) : api.createBriefTemplate(payload);
    },
    onSuccess: (t) => { invalidate(); onSaved(t); },
    onError: (e: Error) => setError(e.message),
  });

  const delMut = useMutation({
    mutationFn: () => api.deleteBriefTemplate(template!.id),
    onSuccess: () => { invalidate(); onClose(); },
  });

  const input = "w-full text-sm border border-ink-line rounded-lg px-2 py-1.5";

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative ml-auto w-[520px] h-full bg-white flex flex-col">
        <div className="px-5 py-4 border-b border-ink-line flex items-center justify-between">
          <h2 className="text-sm font-semibold">{isEdit ? "Править шаблон" : "Новый шаблон"}</h2>
          <button onClick={onClose} className="text-ink-mute hover:text-ink text-lg leading-none">×</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Название</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Инвест-нарратив" className={input} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Тип материала (slug)</label>
            <input value={materialType} onChange={e => setMaterialType(e.target.value)} placeholder="investor_narrative" className={`${input} font-mono`} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Тело промпта (роль + задача + структура + формат)</label>
            <textarea value={body} onChange={e => setBody(e.target.value)} rows={16}
              className={`${input} resize-none font-mono text-xs leading-5`} />
            <p className="text-[11px] text-ink-mute mt-1 leading-snug">
              Постановка аналитика, фактология и правила (green/grey/red + источники) добавляются системой автоматически.
            </p>
          </div>
          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
        </div>
        <div className="px-5 py-4 border-t border-ink-line flex items-center justify-between">
          {isEdit ? (
            <button onClick={() => delMut.mutate()} disabled={delMut.isPending}
              className="text-xs px-3 py-1.5 border border-red-300 text-red-700 rounded-lg hover:bg-red-50">Удалить</button>
          ) : <span />}
          <div className="flex gap-2">
            <button onClick={onClose} className="text-xs px-3 py-1.5 border border-ink-line rounded-lg hover:bg-ink/[0.04]">Отмена</button>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}
              className="text-xs px-3 py-1.5 bg-ink text-white rounded-lg hover:opacity-90 disabled:opacity-50">
              {saveMut.isPending ? "Сохраняю…" : "Сохранить"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
