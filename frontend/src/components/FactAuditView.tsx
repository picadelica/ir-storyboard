import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { readLS, patchLS } from "../persist";
import { RunProgress, useElapsed } from "./RunProgress";
import type { AuditResult, Entity, EntityFact, ReviewFact, DuplicateGroup, AttribItem } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

export default function FactAuditView({ clientId, onJumpToCell }: Props) {
  const qc = useQueryClient();

  // LLM results persist in localStorage (keyed by client), not just component
  // state — so they survive a tab switch / unmount / reload. The write happens
  // inside the mutationFn (not an effect), so the result lands even if the
  // analyst navigated away while the audit was still running; on remount the
  // useState initializer reads it back.
  const lsKey = `fact-audit-${clientId}`;
  const saved = readLS<{
    audit?: AuditResult | null; dups?: DuplicateGroup[] | null;
    attrib?: AttribItem[] | null; founders?: { id: number; name: string }[];
  }>(lsKey);
  const [audit, setAudit] = useState<AuditResult | null>(saved.audit ?? null);
  const [dups, setDups] = useState<DuplicateGroup[] | null>(saved.dups ?? null);
  const dropFromAudit = (id: number) =>
    setAudit(prev => {
      const nx = prev ? { ...prev, facts: prev.facts.filter(f => f.id !== id) } : prev;
      patchLS(lsKey, { audit: nx });
      return nx;
    });
  const dropDupGroup = (pred: (g: DuplicateGroup, i: number) => boolean) =>
    setDups(d => {
      const nx = (d ?? []).filter((g, i) => !pred(g, i));
      patchLS(lsKey, { dups: nx });
      return nx;
    });

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

  const findDups = useMutation({
    mutationFn: async () => {
      const r = await api.findDuplicates(clientId);
      const groups = r.available ? r.groups : [];
      patchLS(lsKey, { dups: groups });   // lands even if unmounted mid-run
      return groups;
    },
    onSuccess: (groups) => setDups(groups),
  });
  // analyst-editable merged wording per group (seeded from the LLM proposal)
  const [mergeText, setMergeText] = useState<Record<number, string>>({});
  // per-group selected fact ids (default = all); lets you merge a subset of 3+ and
  // leave the rest in the matrix.
  const [mergeSel, setMergeSel] = useState<Record<number, Set<number>>>({});
  const selOf = (gi: number, g: DuplicateGroup) => mergeSel[gi] ?? new Set(g.ids);
  const toggleMergeSel = (gi: number, g: DuplicateGroup, id: number) =>
    setMergeSel(m => {
      const cur = new Set(m[gi] ?? new Set(g.ids));
      cur.has(id) ? cur.delete(id) : cur.add(id);
      return { ...m, [gi]: cur };
    });
  const merge = useMutation({
    mutationFn: ({ keep, ids, text }: { gi: number; keep: number; ids: number[]; text?: string }) =>
      api.mergeFacts(keep, ids.filter(i => i !== keep), text),
    onSuccess: (_d, { gi }) => { dropDupGroup((_g, i) => i === gi); invalidate(); },
  });

  // speaker attribution: facts with generic "Фаундер …" wording → name a person
  const [attrib, setAttrib] = useState<AttribItem[] | null>(saved.attrib ?? null);
  const [founders, setFounders] = useState<{ id: number; name: string }[]>(saved.founders ?? []);
  const [attChoice, setAttChoice] = useState<Record<number, number>>({});  // factId → entityId
  const [attNewName, setAttNewName] = useState<Record<number, string>>({}); // factId → typed founder name
  const [attText, setAttText] = useState<Record<number, string>>({});       // factId → edited text
  const dropAttrib = (id: number) =>
    setAttrib(prev => {
      const nx = (prev ?? []).filter(x => x.id !== id);
      patchLS(lsKey, { attrib: nx });
      return nx;
    });
  const findAttrib = useMutation({
    mutationFn: async () => {
      const r = await api.findUnattributed(clientId);
      const items = r.available ? r.items : [];
      patchLS(lsKey, { attrib: items, founders: r.founders });
      return r;
    },
    onSuccess: (r) => { setAttrib(r.available ? r.items : []); setFounders(r.founders); },
  });
  const applyAttrib = useMutation({
    mutationFn: ({ it, entityId, text, newName }: { it: AttribItem; entityId: number | null; text: string; newName?: string }) =>
      api.attributeFact(it.id, entityId, text, newName),
    onSuccess: (_d, { it }) => { qc.invalidateQueries({ queryKey: ["entities", clientId] }); dropAttrib(it.id); invalidate(); },
  });

  const run = useMutation({
    mutationFn: async () => {
      const r = await api.runAudit(clientId);
      patchLS(lsKey, { audit: r });       // lands even if unmounted mid-run
      return r;
    },
    onSuccess: (r) => { setAudit(r); invalidate(); },
  });
  const keep = useMutation({
    mutationFn: (id: number) => api.setVerification(id, { verification: "verified" }),
    onSuccess: (_d, id) => { dropFromAudit(id); invalidate(); },
  });
  const reject = useMutation({
    mutationFn: (id: number) => api.rejectFact(id),
    onSuccess: (_d, id) => { dropFromAudit(id); invalidate(); },
  });
  const pending = audit?.facts ?? [];
  const byEntity = useMemo(() => {
    const m: Record<string, number[]> = {};
    for (const f of pending) {
      const k = f.entity || "—";
      (m[k] ??= []).push(f.id);
    }
    return m;
  }, [pending]);

  const rejectAll = (ids: number[]) => ids.forEach(id => reject.mutate(id));

  const auditElapsed = useElapsed(run.isPending);
  const dupsElapsed = useElapsed(findDups.isPending);
  const attribElapsed = useElapsed(findAttrib.isPending);

  return (
    <div className="p-5 space-y-5 max-w-4xl">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">Проверка фактов</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Скептический аудит research-фактов: склейка сущностей, мис-атрибуция, выдумка.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => findDups.mutate()}
            disabled={findDups.isPending}
            className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50 disabled:opacity-50"
          >
            {findDups.isPending ? "Ищу дубли…" : "Найти дубли"}
          </button>
          <button
            onClick={() => findAttrib.mutate()}
            disabled={findAttrib.isPending}
            title="Найти факты с обезличенным субъектом («фаундер считает…») и проставить имя"
            className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50 disabled:opacity-50"
          >
            {findAttrib.isPending ? "Ищу…" : "Проверить спикеров"}
          </button>
          <button
            onClick={() => run.mutate()}
            disabled={run.isPending}
            className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
          >
            {run.isPending ? "Проверяю…" : "Запустить проверку"}
          </button>
        </div>
      </div>

      <RunProgress active={run.isPending} elapsed={auditElapsed} label="Проверяю факты на склейку сущностей…" />
      <RunProgress active={findDups.isPending} elapsed={dupsElapsed} label="Ищу дубли фактов…" />
      <RunProgress active={findAttrib.isPending} elapsed={attribElapsed} label="Ищу обезличенные формулировки…" />

      {run.isError && (
        <div className="bg-flag-red-bg border border-flag-red/40 rounded p-3 text-sm text-flag-red">
          Проверка не удалась: {(run.error as Error)?.message || "ошибка запроса"}. Попробуй ещё раз.
        </div>
      )}
      {findDups.isError && (
        <div className="bg-flag-red-bg border border-flag-red/40 rounded p-3 text-sm text-flag-red">
          Поиск дублей не удался: {(findDups.error as Error)?.message || "ошибка запроса"}. Попробуй ещё раз.
        </div>
      )}

      {dups !== null && (
        <section className="bg-white rounded-lg border border-ink-line p-4 space-y-3">
          <h3 className="text-sm font-semibold">
            Дубли <span className="font-normal text-ink-mute">({dups.length} групп)</span>
          </h3>
          {dups.length === 0 ? (
            <div className="text-xs text-ink-mute italic">Дублей не найдено (или верификатор недоступен).</div>
          ) : dups.map((g, gi) => {
            const sel = selOf(gi, g);
            const selIds = g.ids.filter(i => sel.has(i));
            // keep = the LLM's keep if still selected, else the first selected fact
            const keep = sel.has(g.keep) ? g.keep : (selIds[0] ?? g.keep);
            const mtext = mergeText[gi] ?? g.merged_text;
            return (
            <div key={gi} className="border border-ink-line rounded p-3">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] font-mono text-ink-mute">{g.subsection_id}</span>
                {g.reason && <span className="text-xs text-ink-mute">· {g.reason}</span>}
                <button onClick={() => onJumpToCell(g.subsection_id)}
                  className="text-[11px] text-blue-600 hover:underline ml-auto">{g.subsection_id} →</button>
              </div>
              {g.ids.length > 2 && (
                <div className="text-[11px] text-ink-mute mb-1">Отметьте, какие факты сливать ({selIds.length} из {g.ids.length}); неотмеченные останутся в матрице.</div>
              )}
              <ul className="space-y-1 mb-2">
                {g.facts.map(f => (
                  <li key={f.id} className="text-sm flex gap-2 items-start">
                    {g.ids.length > 2 && (
                      <input type="checkbox" checked={sel.has(f.id)} onChange={() => toggleMergeSel(gi, g, f.id)} className="mt-1" />
                    )}
                    <span className="text-[10px] mt-0.5 px-1 rounded shrink-0 bg-slate-100 text-ink-mute">#{f.id}</span>
                    <span className={sel.has(f.id) ? "" : "line-through text-ink-mute"}>{f.text}</span>
                  </li>
                ))}
              </ul>
              {/* Proposed single wording — analyst edits before it lands in the matrix.
                  A new merged fact is created with this text; the merged originals are rejected. */}
              <label className="block text-[11px] text-ink-mute mb-1">
                Итоговая формулировка (правится){selIds.length > 2 ? ` — объединяет ${selIds.length} факта` : ""}:
              </label>
              <textarea
                value={mtext}
                onChange={e => setMergeText(m => ({ ...m, [gi]: e.target.value }))}
                rows={2}
                className="w-full text-sm border border-ink-line rounded px-2 py-1.5 mb-2 resize-y"
              />
              <div className="flex flex-wrap gap-2">
                <button onClick={() => merge.mutate({ gi, keep, ids: selIds, text: mtext })}
                  disabled={merge.isPending || selIds.length < 2}
                  className="text-[11px] px-2 py-1 rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">
                  слить с этим текстом ({selIds.length} → 1)
                </button>
                <button onClick={() => merge.mutate({ gi, keep, ids: selIds })}
                  disabled={merge.isPending || selIds.length < 2}
                  title={`Оставить формулировку #${keep} без изменений, просто сложить источники`}
                  className="text-[11px] px-2 py-1 rounded border border-ink-line text-ink-mute hover:bg-slate-50 disabled:opacity-50">
                  оставить #{keep} как есть
                </button>
                <button onClick={() => dropDupGroup((_, i) => i === gi)}
                  className="text-[11px] px-2 py-1 rounded border border-ink-line text-ink-mute hover:bg-slate-50">пропустить</button>
              </div>
            </div>
            );
          })}
        </section>
      )}

      {attrib !== null && (
        <section className="bg-white rounded-lg border border-ink-line p-4 space-y-3">
          <h3 className="text-sm font-semibold">
            Спикеры <span className="font-normal text-ink-mute">({attrib.length} обезличенных)</span>
          </h3>
          {founders.length === 0 && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
              На карточке нет заведённых фаундеров. Впишите имя в поле ниже — карточка фаундера создастся
              автоматически (или добавьте их заранее в «About»).
            </div>
          )}
          {attrib.length === 0 ? (
            <div className="text-xs text-ink-mute italic">Обезличенных формулировок не найдено (или верификатор недоступен).</div>
          ) : attrib.map(it => {
            const chosen = attChoice[it.id] ?? (founders.length === 1 ? founders[0].id : undefined);
            const typed = (attNewName[it.id] ?? "").trim();
            // typed name wins over the dropdown; lets you attribute even with no founder cards
            const effName = typed || founders.find(f => f.id === chosen)?.name;
            const text = attText[it.id]
              ?? (effName ? it.rewrite_template.replace("[ИМЯ]", effName) : it.proposed_text);
            const canApply = !!effName && !text.includes("[ИМЯ]");
            return (
              <div key={it.id} className={`border rounded p-3 ${it.must_be_concrete ? "border-flag-red/40 bg-flag-red-bg/30" : "border-ink-line"}`}>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[11px] font-mono text-ink-mute">{it.subsection_id}</span>
                  {it.must_be_concrete && (
                    <span className="text-[10px] px-1 rounded bg-flag-red/10 text-flag-red" title="L1–L2: обязательно конкретное лицо">L{it.layer_id} — нужно имя</span>
                  )}
                  <button onClick={() => onJumpToCell(it.subsection_id)}
                    className="text-[11px] text-blue-600 hover:underline ml-auto">{it.subsection_id} →</button>
                </div>
                <div className="text-xs text-ink-mute mb-1.5 line-through">{it.text}</div>
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-[11px] text-ink-mute">🗣</span>
                  {founders.length > 0 && (
                    <select
                      value={typed ? "" : (chosen ?? "")}
                      onChange={e => {
                        const eid = e.target.value ? Number(e.target.value) : undefined;
                        setAttChoice(m => ({ ...m, [it.id]: eid as number }));
                        setAttNewName(m => ({ ...m, [it.id]: "" }));
                        const nm = founders.find(f => f.id === eid)?.name;
                        setAttText(m => { const n = { ...m }; delete n[it.id]; return n; });
                        if (nm) setAttText(m => ({ ...m, [it.id]: it.rewrite_template.replace("[ИМЯ]", nm) }));
                      }}
                      className={`text-xs border border-ink-line rounded px-1.5 py-1 bg-white ${chosen && !typed ? "text-ink" : "text-ink-mute"}`}
                    >
                      <option value="">— кто это? —</option>
                      {founders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                    </select>
                  )}
                  <input
                    type="text"
                    value={typed}
                    placeholder={founders.length ? "или впишите имя" : "впишите имя фаундера"}
                    onChange={e => {
                      const v = e.target.value;
                      setAttNewName(m => ({ ...m, [it.id]: v }));
                      setAttText(m => ({ ...m, [it.id]: it.rewrite_template.replace("[ИМЯ]", v.trim() || "[ИМЯ]") }));
                    }}
                    className="text-xs border border-ink-line rounded px-1.5 py-1 bg-white w-44"
                  />
                </div>
                <textarea
                  value={text}
                  onChange={e => setAttText(m => ({ ...m, [it.id]: e.target.value }))}
                  rows={2}
                  className="w-full text-sm border border-ink-line rounded px-2 py-1.5 mb-2 resize-y"
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => applyAttrib.mutate({ it, entityId: typed ? null : (chosen ?? null), text, newName: typed || undefined })}
                    disabled={applyAttrib.isPending || !canApply}
                    className="text-[11px] px-2 py-1 rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">
                    применить имя
                  </button>
                  <button onClick={() => dropAttrib(it.id)}
                    className="text-[11px] px-2 py-1 rounded border border-ink-line text-ink-mute hover:bg-slate-50">пропустить</button>
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* identity anchor */}
      <IdentityAnchor clientId={clientId} entities={entities.data ?? []} />

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
          Верификатор не вернул результат — модель не ответила (бывает при перегрузке).
          Нажми «Запустить проверку» ещё раз. Транскриптные факты не проверяются.
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

const KIND_LABEL: Record<string, string> = { company: "компания", founder: "фаундер", decoy: "двойник" };

function IdentityAnchor({ clientId, entities }: { clientId: string; entities: Entity[] }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const inval = () => qc.invalidateQueries({ queryKey: ["entities", clientId] });
  const create = useMutation({
    mutationFn: (body: { kind: string; name: string; role: string }) => api.createEntity(clientId, body),
    onSuccess: () => { setAdding(false); inval(); },
  });
  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-semibold">Якорь идентичности</h3>
        <span className="text-[11px] text-ink-mute">проверенные факты, вне матрицы</span>
      </div>
      {entities.length === 0 && !adding ? (
        <div className="text-xs text-ink-mute italic mb-2">
          Пусто. Запусти проверку — аудит предложит компанию, фаундеров и двойников. Или добавь карточку вручную.
        </div>
      ) : (
        <div className="space-y-2">
          {entities.map(e => <EntityCard key={e.id} entity={e} onChanged={inval} />)}
        </div>
      )}

      {adding ? (
        <AddEntityForm onCancel={() => setAdding(false)} onSubmit={(b) => create.mutate(b)} busy={create.isPending} />
      ) : (
        <button onClick={() => setAdding(true)}
          className="mt-3 text-[11px] px-2 py-1 rounded border border-dashed border-ink-line text-ink-mute hover:bg-slate-50">
          + добавить карточку
        </button>
      )}
    </section>
  );
}

function EntityCard({ entity: e, onChanged }: { entity: Entity; onChanged: () => void }) {
  const [factOpen, setFactOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const confirm = useMutation({ mutationFn: () => api.patchEntity(e.id, { confirmed: true }), onSuccess: onChanged });
  const remove = useMutation({ mutationFn: () => api.deleteEntity(e.id), onSuccess: onChanged });
  const addFact = useMutation({
    mutationFn: (body: Partial<EntityFact>) => api.addEntityFact(e.id, body),
    onSuccess: () => { setFactOpen(false); onChanged(); },
  });
  const delFact = useMutation({ mutationFn: (fid: number) => api.deleteEntityFact(fid), onSuccess: onChanged });
  const setLinks = useMutation({
    mutationFn: (links: Record<string, string>) => api.patchEntity(e.id, { links }),
    onSuccess: () => { setLinkOpen(false); onChanged(); },
  });

  return (
    <div className={`rounded border p-3 ${e.kind === "decoy" ? "bg-amber-50/60 border-amber-200" : "border-ink-line"}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wide text-ink-mute font-mono">{KIND_LABEL[e.kind] ?? e.kind}</span>
        <span className="text-sm font-medium">{e.name}</span>
        {e.role && <span className="text-xs text-ink-mute">· {e.role}</span>}
        {!e.confirmed && <span className="text-[10px] text-amber-700 bg-amber-100 rounded px-1.5">черновик</span>}
        <div className="ml-auto flex gap-1.5">
          {!e.confirmed && (
            <button onClick={() => confirm.mutate()}
              className="text-[11px] px-2 py-0.5 rounded border border-ink-line hover:bg-slate-50">подтвердить</button>
          )}
          <button onClick={() => remove.mutate()}
            className="text-[11px] px-1.5 py-0.5 text-red-600 hover:text-red-800">удалить</button>
        </div>
      </div>

      {/* links (Wiki / X / LinkedIn …) */}
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {Object.entries(e.links || {}).map(([k, url]) => (
          <span key={k} className="inline-flex items-center gap-1 text-[11px] border border-ink-line rounded px-1.5">
            <a href={url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{k}</a>
            <button onClick={() => { const { [k]: _drop, ...rest } = e.links || {}; setLinks.mutate(rest); }}
              className="text-ink-mute hover:text-red-600">×</button>
          </span>
        ))}
        <button onClick={() => setLinkOpen(v => !v)} className="text-[11px] text-ink-mute hover:text-ink">+ ссылка</button>
      </div>
      {linkOpen && (
        <AddLinkForm busy={setLinks.isPending}
          onSubmit={(label, url) => setLinks.mutate({ ...(e.links || {}), [label]: url })}
          onCancel={() => setLinkOpen(false)} />
      )}

      {e.note && <div className="mt-1 text-xs text-ink-mute">{e.note}</div>}

      {/* facts */}
      {e.facts.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {e.facts.map(f => (
            <li key={f.id} className="text-xs flex gap-2 group">
              {f.key && <span className="text-ink-mute shrink-0">{f.key}:</span>}
              <span className="flex-1">{f.value}</span>
              {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="text-blue-600" title={f.source_title || f.source_url}>↗</a>}
              <button onClick={() => delFact.mutate(f.id)}
                className="text-ink-mute hover:text-red-600 opacity-0 group-hover:opacity-100">×</button>
            </li>
          ))}
        </ul>
      )}

      {factOpen ? (
        <AddFactForm busy={addFact.isPending}
          onSubmit={(body) => addFact.mutate(body)} onCancel={() => setFactOpen(false)} />
      ) : (
        <button onClick={() => setFactOpen(true)}
          className="mt-2 text-[11px] px-2 py-0.5 rounded border border-dashed border-ink-line text-ink-mute hover:bg-slate-50">
          + факт
        </button>
      )}
    </div>
  );
}

function AddFactForm({ onSubmit, onCancel, busy }: {
  onSubmit: (b: Partial<EntityFact>) => void; onCancel: () => void; busy: boolean;
}) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const submit = () => {
    if (!value.trim()) return;
    onSubmit({ key: key.trim(), value: value.trim(), source_url: url.trim(), source_title: title.trim(), verified: !!url.trim() });
  };
  const inp = "text-xs border border-ink-line rounded px-2 py-1 w-full";
  return (
    <div className="mt-2 p-2 rounded bg-slate-50 border border-ink-line space-y-1.5">
      <div className="flex gap-1.5">
        <input className={`${inp} w-28`} placeholder="ключ (напр. Основана)" value={key} onChange={e => setKey(e.target.value)} />
        <input className={inp} placeholder="значение факта *" value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") submit(); }} autoFocus />
      </div>
      <div className="flex gap-1.5">
        <input className={inp} placeholder="ссылка-источник (Wiki/LinkedIn/X)" value={url} onChange={e => setUrl(e.target.value)} />
        <input className={`${inp} w-32`} placeholder="название источника" value={title} onChange={e => setTitle(e.target.value)} />
      </div>
      <div className="flex gap-2 items-center">
        <button onClick={submit} disabled={busy || !value.trim()}
          className="text-[11px] px-2 py-1 rounded bg-ink text-white hover:bg-black disabled:bg-slate-300">{busy ? "…" : "добавить"}</button>
        <button onClick={onCancel} className="text-[11px] text-ink-mute hover:text-ink">отмена</button>
        {!url.trim() && value.trim() && <span className="text-[10px] text-amber-700">без ссылки факт пометится непроверенным</span>}
      </div>
    </div>
  );
}

function AddLinkForm({ onSubmit, onCancel, busy }: {
  onSubmit: (label: string, url: string) => void; onCancel: () => void; busy: boolean;
}) {
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const submit = () => { if (label.trim() && url.trim()) onSubmit(label.trim(), url.trim()); };
  const inp = "text-xs border border-ink-line rounded px-2 py-1";
  return (
    <div className="mt-1.5 flex gap-1.5 items-center">
      <input className={`${inp} w-24`} placeholder="Wiki / X / …" value={label} onChange={e => setLabel(e.target.value)} autoFocus />
      <input className={`${inp} flex-1`} placeholder="https://…" value={url} onChange={e => setUrl(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") submit(); }} />
      <button onClick={submit} disabled={busy || !label.trim() || !url.trim()}
        className="text-[11px] px-2 py-1 rounded bg-ink text-white hover:bg-black disabled:bg-slate-300">ок</button>
      <button onClick={onCancel} className="text-[11px] text-ink-mute hover:text-ink">×</button>
    </div>
  );
}

function AddEntityForm({ onSubmit, onCancel, busy }: {
  onSubmit: (b: { kind: string; name: string; role: string }) => void; onCancel: () => void; busy: boolean;
}) {
  const [kind, setKind] = useState("company");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const submit = () => { if (name.trim()) onSubmit({ kind, name: name.trim(), role: role.trim() }); };
  const inp = "text-xs border border-ink-line rounded px-2 py-1";
  return (
    <div className="mt-3 p-2 rounded bg-slate-50 border border-ink-line flex flex-wrap gap-1.5 items-center">
      <select className={inp} value={kind} onChange={e => setKind(e.target.value)}>
        <option value="company">компания</option>
        <option value="founder">фаундер</option>
        <option value="decoy">двойник</option>
      </select>
      <input className={`${inp} w-40`} placeholder="название *" value={name} onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") submit(); }} autoFocus />
      <input className={`${inp} w-40`} placeholder="роль (напр. CEO)" value={role} onChange={e => setRole(e.target.value)} />
      <button onClick={submit} disabled={busy || !name.trim()}
        className="text-[11px] px-2 py-1 rounded bg-ink text-white hover:bg-black disabled:bg-slate-300">{busy ? "…" : "создать"}</button>
      <button onClick={onCancel} className="text-[11px] text-ink-mute hover:text-ink">отмена</button>
    </div>
  );
}
