import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { AuditResult, Entity, ReviewFact } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

export default function FactAuditView({ clientId, onJumpToCell }: Props) {
  const qc = useQueryClient();
  const [audit, setAudit] = useState<AuditResult | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());

  const entities = useQuery<Entity[]>({
    queryKey: ["entities", clientId],
    queryFn: () => api.entities(clientId),
  });
  const review = useQuery<ReviewFact[]>({
    queryKey: ["review-queue", clientId],
    queryFn: () => api.reviewQueue(clientId),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["facts", clientId] });
    qc.invalidateQueries({ queryKey: ["matrix", clientId] });
    qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    qc.invalidateQueries({ queryKey: ["entities", clientId] });
    qc.invalidateQueries({ queryKey: ["review-queue", clientId] });
  };

  const promote = useMutation({ mutationFn: (id: number) => api.promoteFact(id), onSuccess: invalidate });
  const rejectReview = useMutation({ mutationFn: (id: number) => api.rejectFact(id), onSuccess: invalidate });

  const run = useMutation({
    mutationFn: () => api.runAudit(clientId),
    onSuccess: (r) => { setAudit(r); setDone(new Set()); invalidate(); },
  });
  const keep = useMutation({
    mutationFn: (id: number) => api.setVerification(id, { verification: "verified" }),
    onSuccess: (_d, id) => { setDone(s => new Set(s).add(id)); invalidate(); },
  });
  const reject = useMutation({
    mutationFn: (id: number) => api.rejectFact(id),
    onSuccess: (_d, id) => { setDone(s => new Set(s).add(id)); invalidate(); },
  });
  const confirmEntity = useMutation({
    mutationFn: (id: number) => api.patchEntity(id, { confirmed: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["entities", clientId] }),
  });
  const removeEntity = useMutation({
    mutationFn: (id: number) => api.deleteEntity(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["entities", clientId] }),
  });

  const pending = (audit?.facts ?? []).filter(f => !done.has(f.id));
  const byEntity = useMemo(() => {
    const m: Record<string, number[]> = {};
    for (const f of pending) {
      const k = f.entity || "—";
      (m[k] ??= []).push(f.id);
    }
    return m;
  }, [pending]);

  const rejectAll = (ids: number[]) => ids.forEach(id => reject.mutate(id));

  return (
    <div className="p-5 space-y-5 max-w-4xl">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">Проверка фактов</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Скептический аудит research-фактов: склейка сущностей, мис-атрибуция, выдумка.
          </p>
        </div>
        <button
          onClick={() => run.mutate()}
          disabled={run.isPending}
          className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
        >
          {run.isPending ? "Проверяю…" : "Запустить проверку"}
        </button>
      </div>

      {/* identity anchor */}
      <IdentityAnchor
        entities={entities.data ?? []}
        onConfirm={(id) => confirmEntity.mutate(id)}
        onRemove={(id) => removeEntity.mutate(id)}
      />

      {(review.data?.length ?? 0) > 0 && (
        <section className="bg-white rounded-lg border border-amber-300 p-4 space-y-2">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold text-amber-800">
              На ревью с ингеста <span className="font-normal text-ink-mute">({review.data!.length})</span>
            </h3>
            <span className="text-[11px] text-ink-mute">придержано воротами, не в матрице</span>
          </div>
          <ul className="space-y-2">
            {review.data!.map(f => (
              <li key={f.id} className="border border-ink-line rounded p-3">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  {f.entity && <span className="text-[11px] font-mono text-ink-mute border border-ink-line rounded px-1.5">≠ {f.entity}</span>}
                  <button onClick={() => onJumpToCell(f.subsection_id)}
                    className="text-[11px] text-blue-600 hover:underline ml-auto">{f.subsection_id} →</button>
                </div>
                <div className="text-sm leading-snug">{f.text}</div>
                {f.verification_note && <div className="mt-1 text-xs text-ink-mute border-l-2 border-ink-line pl-2">{f.verification_note}</div>}
                <div className="mt-2 flex gap-2">
                  <button onClick={() => promote.mutate(f.id)}
                    className="text-[11px] px-2 py-1 rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50">в матрицу</button>
                  <button onClick={() => rejectReview.mutate(f.id)}
                    className="text-[11px] px-2 py-1 rounded border border-flag-red/40 text-flag-red hover:bg-flag-red-bg">снять</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {audit && !audit.available && (
        <div className="bg-flag-grey-bg border border-flag-grey/40 rounded p-3 text-sm text-ink-mute">
          Верификатор недоступен (нет ключа LLM или пустой ответ). Транскриптные факты не проверяются.
        </div>
      )}

      {audit?.available && (
        <section className="bg-white rounded-lg border border-ink-line p-4 space-y-3">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold">
              Подозрительные факты <span className="text-ink-mute font-normal">({pending.length} из {audit.n_facts} проверенных)</span>
            </h3>
          </div>
          {audit.summary && <p className="text-xs text-ink-mute italic">{audit.summary}</p>}

          {Object.keys(byEntity).length > 1 && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(byEntity).map(([ent, ids]) => (
                <button key={ent} onClick={() => rejectAll(ids)}
                  className="text-[11px] px-2 py-1 rounded border border-flag-red/40 text-flag-red hover:bg-flag-red-bg">
                  снять все «{ent}» ({ids.length})
                </button>
              ))}
            </div>
          )}

          {pending.length === 0 ? (
            <div className="text-xs text-ink-mute italic py-2">
              {audit.facts.length ? "Все разобраны." : "Подозрительного не найдено."}
            </div>
          ) : (
            <ul className="space-y-2">
              {pending.map(f => (
                <li key={f.id} className="border border-ink-line rounded p-3">
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide
                      ${f.verdict === "refuted" ? "bg-flag-red-bg text-flag-red" : "bg-amber-50 text-amber-700"}`}>
                      {f.verdict === "refuted" ? "опровергнуто" : "под вопросом"}
                    </span>
                    {f.entity && <span className="text-[11px] font-mono text-ink-mute border border-ink-line rounded px-1.5">≠ {f.entity}</span>}
                    <button onClick={() => onJumpToCell(f.subsection_id)}
                      className="text-[11px] text-blue-600 hover:underline ml-auto">{f.subsection_id} →</button>
                  </div>
                  <div className="text-sm leading-snug">{f.text}</div>
                  {f.reason && (
                    <div className="mt-1.5 text-xs text-ink-mute border-l-2 border-ink-line pl-2">{f.reason}</div>
                  )}
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => reject.mutate(f.id)}
                      className="text-[11px] px-2 py-1 rounded border border-flag-red/40 text-flag-red hover:bg-flag-red-bg">снять</button>
                    <button onClick={() => keep.mutate(f.id)}
                      className="text-[11px] px-2 py-1 rounded border border-ink-line text-ink-mute hover:bg-slate-50">оставить</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function IdentityAnchor({ entities, onConfirm, onRemove }: {
  entities: Entity[]; onConfirm: (id: number) => void; onRemove: (id: number) => void;
}) {
  const KIND_LABEL: Record<string, string> = { company: "компания", founder: "фаундер", decoy: "двойник" };
  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-semibold">Якорь идентичности</h3>
        <span className="text-[11px] text-ink-mute">проверенные факты, вне матрицы</span>
      </div>
      {entities.length === 0 ? (
        <div className="text-xs text-ink-mute italic">
          Пусто. Запусти проверку — аудит предложит компанию, фаундеров и двойников.
        </div>
      ) : (
        <div className="space-y-2">
          {entities.map(e => (
            <div key={e.id} className={`rounded border p-3 ${e.kind === "decoy" ? "bg-amber-50/60 border-amber-200" : "border-ink-line"}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] uppercase tracking-wide text-ink-mute font-mono">{KIND_LABEL[e.kind] ?? e.kind}</span>
                <span className="text-sm font-medium">{e.name}</span>
                {e.role && <span className="text-xs text-ink-mute">· {e.role}</span>}
                {!e.confirmed && <span className="text-[10px] text-amber-700 bg-amber-100 rounded px-1.5">черновик</span>}
                <div className="ml-auto flex gap-1.5">
                  {!e.confirmed && (
                    <button onClick={() => onConfirm(e.id)}
                      className="text-[11px] px-2 py-0.5 rounded border border-ink-line hover:bg-slate-50">подтвердить</button>
                  )}
                  <button onClick={() => onRemove(e.id)}
                    className="text-[11px] px-1.5 py-0.5 text-red-600 hover:text-red-800">удалить</button>
                </div>
              </div>
              {Object.keys(e.links || {}).length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {Object.entries(e.links).map(([k, url]) => (
                    <a key={k} href={url} target="_blank" rel="noreferrer"
                      className="text-[11px] text-blue-600 hover:underline border border-ink-line rounded px-1.5">{k}</a>
                  ))}
                </div>
              )}
              {e.note && <div className="mt-1 text-xs text-ink-mute">{e.note}</div>}
              {e.facts.length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {e.facts.map(f => (
                    <li key={f.id} className="text-xs flex gap-2">
                      {f.key && <span className="text-ink-mute">{f.key}:</span>}
                      <span className="flex-1">{f.value}</span>
                      {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="text-blue-600">↗</a>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
