import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import type { ArtifactSummary } from "../types";

interface Props {
  clientId: string;
  pickedArtifactId?: number;
}

export default function ArtifactsView({ clientId, pickedArtifactId }: Props) {
  const [selected, setSelected] = useState<number | null>(pickedArtifactId ?? null);
  const [bundleIds, setBundleIds] = useState<Set<number>>(new Set());

  useEffect(() => { if (pickedArtifactId) setSelected(pickedArtifactId); }, [pickedArtifactId]);

  const list = useQuery<ArtifactSummary[]>({
    queryKey: ["artifacts", clientId],
    queryFn: () => api.listArtifacts(clientId),
  });

  const artifact = useQuery({
    queryKey: ["artifact", selected],
    queryFn: () => api.getArtifact(selected!),
    enabled: !!selected,
  });

  useEffect(() => {
    if (selected === null && list.data && list.data.length > 0) {
      setSelected(list.data[0].id);
    }
  }, [list.data, selected]);

  const toggleBundle = (id: number) => {
    setBundleIds(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  const bundleIdsArray = Array.from(bundleIds);

  return (
    <div className="grid grid-cols-[20rem_1fr] gap-5 p-5 h-full">
      {/* Sidebar list */}
      <div className="border-r border-ink-line pr-5 overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Артефакты</h2>
          <a
            href={bundleIdsArray.length > 0 ? api.notebooklmBundleUrl(clientId, bundleIdsArray) : undefined}
            className={`text-[11px] px-2 py-1 rounded ${bundleIdsArray.length > 0
              ? "bg-emerald-700 text-white hover:bg-emerald-800"
              : "bg-slate-200 text-ink-mute pointer-events-none"}`}
          >
            ↓ NotebookLM bundle ({bundleIdsArray.length})
          </a>
        </div>

        {list.isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
        {list.data?.length === 0 && (
          <div className="text-sm text-ink-mute italic">
            No artifacts yet. Run a cycle from the sidebar.
          </div>
        )}
        <ul className="space-y-1.5">
          {list.data?.map(a => (
            <li
              key={a.id}
              className={`relative rounded border px-2.5 py-2 cursor-pointer transition
                ${selected === a.id ? "border-ink bg-slate-50" : "border-ink-line hover:bg-slate-50"}`}
              onClick={() => setSelected(a.id)}
            >
              <div className="flex items-center justify-between">
                <span className="inline-block text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-200">
                  {a.cycle}
                </span>
                <input
                  type="checkbox"
                  checked={bundleIds.has(a.id)}
                  onChange={(e) => { e.stopPropagation(); toggleBundle(a.id); }}
                  onClick={(e) => e.stopPropagation()}
                  className="w-4 h-4"
                  title="Добавить в пакет NotebookLM"
                />
              </div>
              <div className="text-xs font-medium leading-tight mt-1">{a.title}</div>
              <div className="text-[10px] font-mono text-ink-mute mt-1">
                {a.created_at.replace("T", " ").slice(0, 16)}
              </div>
            </li>
          ))}
        </ul>
      </div>

      {/* Body */}
      <div className="overflow-y-auto bg-white rounded-lg border border-ink-line p-6">
        {!selected && <div className="text-sm text-ink-mute">Выберите артефакт слева.</div>}
        {artifact.isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
        {artifact.data && (
          <article className="prose-md max-w-none">
            <ReactMarkdown>{artifact.data.body}</ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}
