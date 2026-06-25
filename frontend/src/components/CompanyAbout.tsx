import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { RunProgress, useElapsed } from "./RunProgress";
import type { Entity, EntityFact, Client, AboutProposal, AboutAutofillResult, FounderProposal, FounderDiscoverResult } from "../types";

interface Props {
  clientId: string;
}

// The company "About" — a structured business profile (no narrative), kept as a
// distinct entity and filled by hand (and, later, by ingest). Facts are grouped
// into fixed business sections; every fact is source-linked.
// Официальные ссылки (сайт / wiki / соцсети) живут в шапке (entity.links), не в секциях.
const SECTIONS: { id: string; label: string; hint: string; keyPh: string; valPh: string }[] = [
  { id: "profile", label: "Профиль", hint: "юр. название, основана, стадия, команда, чем занимается", keyPh: "напр. Основана", valPh: "2021, Сан-Франциско" },
  { id: "funding", label: "Финансирование", hint: "раунд: стадия, сумма, дата, лид/инвесторы, оценка", keyPh: "напр. Seed", valPh: "$18M, 2024, лид Coatue" },
  { id: "history", label: "История / майлстоны", hint: "датированные бизнес-события: запуски, релизы, сделки", keyPh: "напр. Запуск", valPh: "что и когда произошло" },
  { id: "product", label: "Продукт и рынок", hint: "продукт, категория/рынок, конкуренты", keyPh: "напр. Продукт", valPh: "что это и для кого" },
  { id: "metrics", label: "Метрики", hint: "ключевые числа: ARR, пользователи, рост (с датой)", keyPh: "напр. ARR", valPh: "$2M (Q1 2026)" },
];

// Технические ключи из авто-наполнения → человеческие подписи. Ключи приходят
// шумные: founded_date_fintech, funding_round_a_crunchbase. Срезаем шумовые/
// источниковые суффиксы, мапим базу; неизвестный технический ключ скрываем
// (значение само себя описывает: «Founded 2022», «Miami, Florida»).
const KEY_BASE: Record<string, string> = {
  company_name: "Название", name: "Название", legal_name: "Юр. название",
  founded_date: "Основана", founded: "Основана", founding_year: "Основана", founding_date: "Основана",
  headquarters: "Штаб-квартира", hq: "Штаб-квартира", location: "Локация",
  business_description: "Описание", description: "Описание", overview: "Описание",
  founder: "Фаундер", founders: "Фаундеры", ceo: "CEO", cto: "CTO",
  website: "Сайт", site: "Сайт", url: "Сайт", domain: "Домен",
  linkedin: "LinkedIn", twitter: "X", x: "X", github: "GitHub", crunchbase: "Crunchbase",
  funding_round: "Раунд", funding: "Финансирование", round: "Раунд",
  valuation: "Оценка", investors: "Инвесторы", lead_investor: "Лид-инвестор",
  product_category: "Категория", category: "Категория", product: "Продукт",
  target_market: "Рынок", market: "Рынок", competitors: "Конкуренты",
  key_feature: "Функция", feature: "Функция",
  arr: "ARR", mrr: "MRR", revenue: "Выручка", users: "Пользователи", customers: "Клиенты",
  employees: "Команда", team_size: "Команда", headcount: "Команда", stage: "Стадия", growth: "Рост",
};
// слова-«шум» в хвосте ключа: сектор/источник, не несут смысла как ярлык
const KEY_NOISE = new Set(["fintech", "crunchbase", "pitchbook", "yahoo", "calcalistech",
  "startuphub", "linkedin", "source", "src", "official", "inc", "co", "data", "info"]);

// Фаундеры, упомянутые ФАКТАМИ карточки (key=founder / «… founder/CEO …») —
// чтобы предложить добавить их в блок «Фаундеры» в один клик.
type FounderHint = { name: string; role: string; source_url: string };
function founderCandidates(facts: EntityFact[]): FounderHint[] {
  const out: FounderHint[] = [];
  const seen = new Set<string>();
  for (const f of facts) {
    const k = (f.key || "").toLowerCase();
    const v = (f.value || "").trim();
    const keyHit = /founder|cofounder|co_founder|ceo/.test(k);
    const valHit = /\b(co-?founder|founder|ceo|основател)/i.test(v);
    if (!keyHit && !valHit) continue;
    // «Dave Waiser (ex-Gett CEO)» → name=«Dave Waiser», role=«ex-Gett CEO»
    let body = v.replace(/^(founded by|founder[:\s]+|co-?founder[:\s]+|ceo[:\s]+)/i, "").trim();
    const m = body.match(/^([^(,]+?)\s*(?:[(,]\s*([^)]*?)\)?\s*)?$/);
    const name = (m ? m[1] : body).trim();
    const role = (m && m[2] ? m[2] : "").trim();
    if (!name || name.length > 60 || seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    out.push({ name, role, source_url: f.source_url || "" });
  }
  return out;
}

function humanizeKey(k: string): string {
  const raw = (k || "").trim();
  if (!raw) return "";
  // человеческий ключ (пробелы / заглавные / кириллица) — оставляем как есть
  if (!/^[a-z0-9_]+$/.test(raw.toLowerCase())) return raw;
  let toks = raw.toLowerCase().split("_").filter(Boolean);
  while (toks.length > 1 && KEY_NOISE.has(toks[toks.length - 1])) toks.pop();
  // ищем известную базу, сокращая хвост: funding_round_a → «Раунд» + «A»
  for (let n = toks.length; n >= 1; n--) {
    const base = toks.slice(0, n).join("_");
    if (KEY_BASE[base]) {
      const rest = toks.slice(n).map(t => (t.length <= 2 ? t.toUpperCase() : t));
      return rest.length ? `${KEY_BASE[base]} ${rest.join(" ")}` : KEY_BASE[base];
    }
  }
  return "";   // неизвестный технический ключ → скрываем, показываем только значение
}

export default function CompanyAbout({ clientId }: Props) {
  const qc = useQueryClient();
  const entities = useQuery<Entity[]>({ queryKey: ["entities", clientId], queryFn: () => api.entities(clientId) });
  const client = useQuery<Client>({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const inval = () => qc.invalidateQueries({ queryKey: ["entities", clientId] });

  const company = (entities.data ?? []).find(e => e.kind === "company") ?? null;

  const createCompany = useMutation({
    mutationFn: () => api.createEntity(clientId, { kind: "company", name: client.data?.name || clientId, confirmed: true }),
    onSuccess: inval,
  });

  if (entities.isLoading) return <div className="p-5 text-sm text-ink-mute">Загрузка…</div>;

  if (!company) {
    return (
      <div className="p-5 max-w-3xl">
        <h2 className="text-lg font-semibold mb-1">О компании</h2>
        <p className="text-sm text-ink-mute mb-4">
          Структурный бизнес-профиль компании — голые факты со ссылками, без нарратива.
        </p>
        <button onClick={() => createCompany.mutate()} disabled={createCompany.isPending}
          className="text-sm px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">
          {createCompany.isPending ? "Создаю…" : "Создать карточку компании"}
        </button>
      </div>
    );
  }

  const bySection = (sid: string) => (company.facts || []).filter(f => (f.section || "") === sid);
  // ссылки секции «sites» переезжают в шапку как официальные ссылки
  const siteFacts = (company.facts || []).filter(f => (f.section || "") === "sites");
  const ungrouped = (company.facts || []).filter(f =>
    (f.section || "") !== "sites" && !SECTIONS.some(s => s.id === (f.section || "")));

  return (
    <div className="p-5 max-w-5xl space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-ink-mute">Голые бизнес-факты со ссылками. Без нарратива.</p>
        <Autofill clientId={clientId} onCommitted={inval} />
      </div>
      <CompanyHeader company={company} siteFacts={siteFacts} onChanged={inval} />
      <FoundersBlock clientId={clientId} founders={(entities.data ?? []).filter(e => e.kind === "founder")}
        candidates={founderCandidates(company.facts || [])} onChanged={inval} />
      {/* секции в две колонки — используем ширину экрана */}
      <div className="grid md:grid-cols-2 gap-4 items-start">
        {SECTIONS.map(s => (
          <SectionBlock key={s.id} section={s} entityId={company.id} facts={bySection(s.id)} onChanged={inval} />
        ))}
        {ungrouped.length > 0 && (
          <SectionBlock section={{ id: "", label: "Прочее", hint: "факты без секции", keyPh: "ключ", valPh: "значение" }}
            entityId={company.id} facts={ungrouped} onChanged={inval} />
        )}
      </div>
    </div>
  );
}

// Founders list — kind='founder' entities of the company. They're who facts get
// attributed to (the "кто говорит" picker on each fact in the cell drawer).
function FoundersBlock({ clientId, founders, candidates = [], onChanged }: { clientId: string; founders: Entity[]; candidates?: FounderHint[]; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const create = useMutation({
    mutationFn: () => api.createEntity(clientId, { kind: "founder", name: name.trim(), role: role.trim(), confirmed: true }),
    onSuccess: () => { setAdding(false); setName(""); setRole(""); onChanged(); },
  });
  const addHint = useMutation({
    mutationFn: (c: FounderHint) => api.createEntity(clientId, { kind: "founder", name: c.name, role: c.role, confirmed: true }),
    onSuccess: onChanged,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteEntity(id), onSuccess: onChanged });
  const inp = "text-xs border border-ink-line rounded px-2 py-1";
  const have = new Set(founders.map(f => (f.name || "").toLowerCase().trim()));
  const hints = candidates.filter(c => !have.has(c.name.toLowerCase().trim()));

  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-semibold">Фаундеры</h3>
          <span className="text-[11px] text-ink-mute">к ним привязываются факты — кто именно говорит</span>
        </div>
        <FounderDiscovery clientId={clientId} existing={founders} onChanged={onChanged} />
      </div>
      {hints.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-ink-mute">упомянуты в фактах:</span>
          {hints.map((c, i) => (
            <button key={i} onClick={() => addHint.mutate(c)} disabled={addHint.isPending}
              title={c.role ? `${c.name} · ${c.role} — добавить фаундером` : `${c.name} — добавить фаундером`}
              className="text-[11px] px-2 py-0.5 rounded border border-flag-blue/40 text-flag-blue hover:bg-flag-blue/5">
              + {c.name}{c.role && <span className="text-ink-mute"> · {c.role}</span>}
            </button>
          ))}
        </div>
      )}
      {founders.length === 0 ? (
        <div className="text-xs text-ink-mute italic py-1">Пусто. Добавь вручную, кликни подсказку выше или нажми «Найти фаундеров».</div>
      ) : (
        <ul className="space-y-1 py-1">
          {founders.map(f => (
            <li key={f.id} className="text-sm flex items-baseline gap-2 group">
              <span className="font-medium">{f.name}</span>
              {f.role && <span className="text-xs text-ink-mute">· {f.role}</span>}
              {Object.entries(f.links || {}).map(([k, url]) => (
                <a key={k} href={url} target="_blank" rel="noreferrer" className="text-[11px] text-blue-600 hover:underline">{k}</a>
              ))}
              <button onClick={() => remove.mutate(f.id)}
                className="ml-auto text-ink-mute hover:text-red-600 opacity-0 group-hover:opacity-100 text-xs">удалить</button>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="mt-2 flex flex-wrap gap-1.5 items-center">
          <input className={`${inp} w-40`} placeholder="имя фаундера *" value={name} onChange={e => setName(e.target.value)} autoFocus
            onKeyDown={e => { if (e.key === "Enter" && name.trim()) create.mutate(); }} />
          <input className={`${inp} w-36`} placeholder="роль (напр. CEO)" value={role} onChange={e => setRole(e.target.value)} />
          <button onClick={() => create.mutate()} disabled={create.isPending || !name.trim()}
            className="text-[11px] px-2 py-1 rounded bg-ink text-white hover:bg-black disabled:bg-slate-300">{create.isPending ? "…" : "добавить"}</button>
          <button onClick={() => setAdding(false)} className="text-[11px] text-ink-mute hover:text-ink">отмена</button>
        </div>
      ) : (
        <button onClick={() => setAdding(true)}
          className="mt-2 text-[11px] px-2 py-0.5 rounded border border-dashed border-ink-line text-ink-mute hover:bg-slate-50">+ фаундер вручную</button>
      )}
    </section>
  );
}

// Авто-поиск фаундеров: веб + LLM предлагают имена и профили; аналитик отмечает,
// кого внести. Каждый профиль-ссылка обоснован веб-источником (см. company.py).
function FounderDiscovery({ clientId, existing, onChanged }: { clientId: string; existing: Entity[]; onChanged: () => void }) {
  const [result, setResult] = useState<FounderDiscoverResult | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const have = new Set(existing.map(e => (e.name || "").toLowerCase().trim()));
  const run = useMutation({
    mutationFn: () => api.discoverFounders(clientId),
    onSuccess: (r) => {
      setResult(r);
      // по умолчанию отмечаем тех, кого ещё нет на карточке
      setAccepted(new Set(r.founders.map((f, i) => have.has(f.name.toLowerCase().trim()) ? -1 : i).filter(i => i >= 0)));
    },
  });
  const elapsed = useElapsed(run.isPending);
  const commit = useMutation({
    mutationFn: async (picked: FounderProposal[]) => {
      for (const f of picked) {
        await api.createEntity(clientId, { kind: "founder", name: f.name, role: f.role, links: f.links, confirmed: true });
      }
      return picked.length;
    },
    onSuccess: () => { setResult(null); setAccepted(new Set()); onChanged(); },
  });
  const founders = result?.founders ?? [];
  const toggle = (i: number) => setAccepted(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });

  return (
    <>
      <button onClick={() => run.mutate()} disabled={run.isPending}
        className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50 disabled:opacity-50 shrink-0">
        {run.isPending ? "Ищу…" : "Найти фаундеров"}
      </button>

      {(run.isPending || result || run.isError) && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => { if (!run.isPending && !commit.isPending) { setResult(null); run.reset(); } }}>
          <div className="bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4 p-4 space-y-3" onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Найденные фаундеры — на проверку</h3>
              <button onClick={() => { setResult(null); run.reset(); }} className="text-ink-mute hover:text-ink text-sm">✕</button>
            </div>

            <RunProgress active={run.isPending} elapsed={elapsed} expected={60}
              label="Ищу фаундеров и профили в вебе…" />
            {run.isError && <div className="text-sm text-flag-red">Не удалось: {(run.error as Error)?.message}. Попробуй ещё раз.</div>}

            {result && !result.available && (
              <div className="text-sm text-ink-mute">Поиск не дал результата (перегруз или нет ключа). Попробуй ещё раз.</div>
            )}
            {result?.available && founders.length === 0 && (
              <div className="text-sm text-ink-mute">Не нашли фаундеров с источниками в вебе. Добавь вручную.</div>
            )}

            {result?.available && founders.length > 0 && (
              <>
                <p className="text-[11px] text-ink-mute">
                  Веб-хитов: {result.stats.from_web}{result.stats.dropped_ungrounded > 0 && ` · отброшено без источника: ${result.stats.dropped_ungrounded}`}.
                  Каждая ссылка-профиль — из реального источника, проверь перед добавлением.
                </p>
                <div className="max-h-[55vh] overflow-y-auto space-y-2">
                  {founders.map((f, i) => {
                    const dup = have.has(f.name.toLowerCase().trim());
                    return (
                      <label key={i} className={`flex gap-2 items-start p-2 rounded border cursor-pointer ${accepted.has(i) ? "border-ink/30 bg-slate-50" : "border-ink-line"}`}>
                        <input type="checkbox" checked={accepted.has(i)} onChange={() => toggle(i)} className="mt-1" />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm flex items-baseline gap-2 flex-wrap">
                            <span className="font-medium">{f.name}</span>
                            {f.role && <span className="text-xs text-ink-mute">· {f.role}</span>}
                            {dup && <span className="text-[10px] px-1 rounded bg-amber-50 text-amber-700">уже на карточке</span>}
                          </div>
                          <div className="mt-0.5 flex flex-wrap gap-2 items-center">
                            {Object.entries(f.links || {}).length === 0
                              ? <span className="text-[11px] text-ink-mute italic">профили не найдены — добавишь вручную</span>
                              : Object.entries(f.links).map(([k, url]) => (
                                  <a key={k} href={url} target="_blank" rel="noreferrer" className="text-[11px] text-blue-600 hover:underline">{k} ↗</a>
                                ))}
                          </div>
                        </div>
                        {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="text-blue-600 shrink-0 text-sm" title="источник">↗</a>}
                      </label>
                    );
                  })}
                </div>
                <div className="flex gap-2 items-center pt-1">
                  <button
                    onClick={() => commit.mutate(founders.filter((_, i) => accepted.has(i)))}
                    disabled={commit.isPending || accepted.size === 0}
                    className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">
                    {commit.isPending ? "Добавляю…" : `Добавить отмеченных (${accepted.size})`}
                  </button>
                  <button onClick={() => { setResult(null); run.reset(); }} className="text-xs text-ink-mute hover:text-ink">отмена</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

const SECTION_LABEL: Record<string, string> = {
  profile: "Профиль", sites: "Сайты и каналы", funding: "Финансирование",
  history: "История / майлстоны", product: "Продукт и рынок", metrics: "Метрики",
};

// Source-grounded auto-fill: a background job proposes business facts (from the
// client's collected facts + web search), the analyst accepts what to keep, only
// then it lands. Every proposal carries a real source link — verify before accept.
type AutofillOpts = { pasted?: string; pasted_url?: string; pasted_title?: string; use_web?: boolean };

function Autofill({ clientId, onCommitted }: { clientId: string; onCommitted: () => void }) {
  const [result, setResult] = useState<AboutAutofillResult | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [docOpen, setDocOpen] = useState(false);
  const [pasted, setPasted] = useState("");
  const [pUrl, setPUrl] = useState("");
  const [pTitle, setPTitle] = useState("");
  const run = useMutation({
    mutationFn: (opts: AutofillOpts) => api.autofillCompany(clientId, opts),
    onSuccess: (r) => { setResult(r); setAccepted(new Set(r.proposals.map((_, i) => i))); },
  });
  const elapsed = useElapsed(run.isPending);
  const commit = useMutation({
    mutationFn: (picked: AboutProposal[]) => api.commitCompanyFacts(clientId, picked),
    onSuccess: () => { setResult(null); setAccepted(new Set()); onCommitted(); },
  });

  const proposals = result?.proposals ?? [];
  const bySec: Record<string, { p: AboutProposal; i: number }[]> = {};
  proposals.forEach((p, i) => (bySec[p.section] ??= []).push({ p, i }));
  const toggle = (i: number) => setAccepted(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const submitDoc = () => {
    if (!pasted.trim() || !pUrl.trim()) return;
    setDocOpen(false);
    run.mutate({ pasted: pasted.trim(), pasted_url: pUrl.trim(), pasted_title: pTitle.trim(), use_web: false });
  };

  return (
    <>
      <div className="flex gap-2 shrink-0">
        <button onClick={() => setDocOpen(true)} disabled={run.isPending}
          className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50 disabled:opacity-50">
          Из документа
        </button>
        <button onClick={() => run.mutate({ use_web: true })} disabled={run.isPending}
          className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">
          {run.isPending ? "Ищу…" : "Авто-наполнить"}
        </button>
      </div>

      {docOpen && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => setDocOpen(false)}>
          <div className="bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4 p-4 space-y-2" onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Из документа</h3>
              <button onClick={() => setDocOpen(false)} className="text-ink-mute hover:text-ink text-sm">✕</button>
            </div>
            <p className="text-[11px] text-ink-mute">Вставь текст (deep-research отчёт, статья) и URL источника — факты будут привязаны к этой ссылке.</p>
            <input className="text-xs border border-ink-line rounded px-2 py-1 w-full" placeholder="URL источника * (https://…)" value={pUrl} onChange={e => setPUrl(e.target.value)} />
            <input className="text-xs border border-ink-line rounded px-2 py-1 w-full" placeholder="название источника (необязательно)" value={pTitle} onChange={e => setPTitle(e.target.value)} />
            <textarea className="text-xs border border-ink-line rounded px-2 py-1 w-full h-48" placeholder="вставь текст документа *" value={pasted} onChange={e => setPasted(e.target.value)} />
            <div className="flex gap-2 items-center">
              <button onClick={submitDoc} disabled={!pasted.trim() || !pUrl.trim()}
                className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">Извлечь факты</button>
              <button onClick={() => setDocOpen(false)} className="text-xs text-ink-mute hover:text-ink">отмена</button>
              {pasted.trim() && !pUrl.trim() && <span className="text-[10px] text-amber-700">нужен URL источника для привязки фактов</span>}
            </div>
          </div>
        </div>
      )}

      {(run.isPending || result || run.isError) && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => { if (!run.isPending && !commit.isPending) { setResult(null); run.reset(); } }}>
          <div className="bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4 p-4 space-y-3" onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Авто-наполнение — предложения</h3>
              <button onClick={() => { setResult(null); run.reset(); }} className="text-ink-mute hover:text-ink text-sm">✕</button>
            </div>

            <RunProgress active={run.isPending} elapsed={elapsed} expected={90}
              label="Собираю факты из источников…" />
            {run.isError && <div className="text-sm text-flag-red">Не удалось: {(run.error as Error)?.message}. Попробуй ещё раз.</div>}

            {result && !result.available && (
              <div className="text-sm text-ink-mute">Верификатор не ответил (перегруз или нет ключа). Попробуй ещё раз.</div>
            )}
            {result?.available && proposals.length === 0 && (
              <div className="text-sm text-ink-mute">
                Нечего предложить — нет фактов с источниками для этой компании.
                {result.stats.dropped_ungrounded > 0 && ` Отброшено без источника: ${result.stats.dropped_ungrounded}.`}
              </div>
            )}

            {result?.available && proposals.length > 0 && (
              <>
                <p className="text-[11px] text-ink-mute">
                  Из матрицы: {result.stats.from_matrix} · веб-хитов: {result.stats.from_web}
                  {result.stats.dropped_ungrounded > 0 && ` · отброшено без источника: ${result.stats.dropped_ungrounded}`}.
                  Отметь, что внести — каждый факт со ссылкой, проверь перед принятием.
                </p>
                <div className="max-h-[55vh] overflow-y-auto space-y-3">
                  {Object.entries(bySec).map(([sec, items]) => (
                    <div key={sec}>
                      <div className="text-xs font-semibold mb-1">{SECTION_LABEL[sec] ?? sec}</div>
                      <ul className="space-y-1">
                        {items.map(({ p, i }) => (
                          <li key={i} className="flex gap-2 text-sm items-baseline">
                            <input type="checkbox" checked={accepted.has(i)} onChange={() => toggle(i)} className="mt-1" />
                            {p.key && <span className="text-ink-mute shrink-0 min-w-[80px]">{humanizeKey(p.key)}</span>}
                            <span className="flex-1">{p.value}{p.as_of && <span className="text-[11px] text-ink-mute"> · {p.as_of}</span>}</span>
                            <span className={`text-[10px] px-1 rounded shrink-0 ${p.origin === "matrix" ? "bg-slate-100 text-ink-mute" : "bg-blue-50 text-blue-700"}`}>{p.origin === "web" ? "веб" : p.origin === "doc" ? "документ" : "матрица"}</span>
                            <a href={p.source_url} target="_blank" rel="noreferrer" className="text-blue-600 shrink-0" title={p.source_title || p.source_url}>↗</a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2 items-center pt-1">
                  <button
                    onClick={() => commit.mutate(proposals.filter((_, i) => accepted.has(i)))}
                    disabled={commit.isPending || accepted.size === 0}
                    className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">
                    {commit.isPending ? "Вношу…" : `Внести отмеченные (${accepted.size})`}
                  </button>
                  <button onClick={() => { setResult(null); run.reset(); }} className="text-xs text-ink-mute hover:text-ink">отмена</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function CompanyHeader({ company: e, siteFacts = [], onChanged }: { company: Entity; siteFacts?: EntityFact[]; onChanged: () => void }) {
  const [linkOpen, setLinkOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(e.name);
  const [role, setRole] = useState(e.role || "");
  const [note, setNote] = useState(e.note || "");
  const setLinks = useMutation({
    mutationFn: (links: Record<string, string>) => api.patchEntity(e.id, { links }),
    onSuccess: () => { setLinkOpen(false); onChanged(); },
  });
  const delFact = useMutation({ mutationFn: (fid: number) => api.deleteEntityFact(fid), onSuccess: onChanged });
  // href из факта-ссылки: значение-URL, иначе source_url, иначе домен → https://
  const factHref = (f: EntityFact) => {
    const v = (f.value || "").trim();
    if (/^https?:\/\//i.test(v)) return v;
    if (f.source_url) return f.source_url;
    return v ? `https://${v.replace(/^\/+/, "")}` : "#";
  };
  const hasAnyLink = Object.keys(e.links || {}).length > 0 || siteFacts.length > 0;
  const saveHead = useMutation({
    mutationFn: () => api.patchEntity(e.id, { name: name.trim() || e.name, role: role.trim(), note: note.trim() }),
    onSuccess: () => { setEditing(false); onChanged(); },
  });
  const inp = "text-sm border border-ink-line rounded px-2 py-1";

  if (editing) {
    return (
      <div className="bg-white rounded-lg border border-ink-line p-4 space-y-2">
        <div className="flex gap-2 flex-wrap">
          <input className={`${inp} w-48`} placeholder="название *" value={name} onChange={ev => setName(ev.target.value)} autoFocus />
          <input className={`${inp} w-48`} placeholder="роль / одной строкой" value={role} onChange={ev => setRole(ev.target.value)} />
        </div>
        <input className={`${inp} w-full`} placeholder="заметка (необязательно)" value={note} onChange={ev => setNote(ev.target.value)} />
        <div className="flex gap-2 items-center">
          <button onClick={() => saveHead.mutate()} disabled={saveHead.isPending || !name.trim()}
            className="text-[11px] px-2 py-1 rounded bg-ink text-white hover:bg-black disabled:bg-slate-300">{saveHead.isPending ? "…" : "сохранить"}</button>
          <button onClick={() => { setName(e.name); setRole(e.role || ""); setNote(e.note || ""); setEditing(false); }}
            className="text-[11px] text-ink-mute hover:text-ink">отмена</button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h2 className="text-lg font-semibold">{e.name}</h2>
        {e.role && <span className="text-sm text-ink-mute">· {e.role}</span>}
        <button onClick={() => setEditing(true)} className="text-ink-mute hover:text-ink text-xs" title="править заголовок">✎</button>
        <span className="ml-auto text-[11px] text-ink-mute">бизнес-профиль · без нарратива</span>
      </div>
      {e.note && <div className="mt-1 text-xs text-ink-mute">{e.note}</div>}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-ink-mute/80 mr-0.5">Официальные ссылки:</span>
        {!hasAnyLink && (
          <span className="text-[11px] text-ink-mute italic">пока нет — добавь сайт, Wikipedia, соцсети</span>
        )}
        {/* ссылки-факты (секция sites) */}
        {siteFacts.map(f => (
          <span key={`f${f.id}`} className="inline-flex items-center gap-1 text-[11px] border border-ink-line rounded px-1.5 py-0.5">
            <a href={factHref(f)} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{humanizeKey(f.key) || f.value || "ссылка"}</a>
            <button onClick={() => delFact.mutate(f.id)} className="text-ink-mute hover:text-red-600">×</button>
          </span>
        ))}
        {/* ссылки entity.links */}
        {Object.entries(e.links || {}).map(([k, url]) => (
          <span key={k} className="inline-flex items-center gap-1 text-[11px] border border-ink-line rounded px-1.5 py-0.5">
            <a href={url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{k}</a>
            <button onClick={() => { const { [k]: _d, ...rest } = e.links || {}; setLinks.mutate(rest); }}
              className="text-ink-mute hover:text-red-600">×</button>
          </span>
        ))}
        <button onClick={() => setLinkOpen(v => !v)} className="text-[11px] text-ink-mute hover:text-ink border border-dashed border-ink-line rounded px-1.5 py-0.5">+ ссылка</button>
      </div>
      {linkOpen && (
        <LinkForm busy={setLinks.isPending}
          onSubmit={(label, url) => setLinks.mutate({ ...(e.links || {}), [label]: url })}
          onCancel={() => setLinkOpen(false)} />
      )}
    </div>
  );
}

function SectionBlock({ section, entityId, facts, onChanged }: {
  section: { id: string; label: string; hint: string; keyPh: string; valPh: string };
  entityId: number; facts: EntityFact[]; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const addFact = useMutation({
    mutationFn: (body: Partial<EntityFact>) => api.addEntityFact(entityId, { ...body, section: section.id }),
    onSuccess: () => { setOpen(false); onChanged(); },
  });
  const delFact = useMutation({ mutationFn: (fid: number) => api.deleteEntityFact(fid), onSuccess: onChanged });

  return (
    <section className="bg-white rounded-lg border border-ink-line p-4">
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <h3 className="text-sm font-semibold">{section.label}</h3>
        <span className="text-[11px] text-ink-mute text-right">{section.hint}</span>
      </div>
      {facts.length === 0 ? (
        <div className="text-xs text-ink-mute italic py-1">Пусто.</div>
      ) : (
        <ul className="space-y-1 py-1">
          {facts.map(f => {
            const label = humanizeKey(f.key);
            return (
            <li key={f.id} className="text-sm flex gap-2.5 group items-start">
              {label && <span className="shrink-0 w-24 text-[11px] uppercase tracking-wide text-ink-mute pt-[3px] leading-tight">{label}</span>}
              <span className="flex-1 min-w-0 leading-snug break-words">{f.value}{f.as_of && <span className="text-[11px] text-ink-mute"> · {f.as_of}</span>}</span>
              {f.source_url
                ? <a href={f.source_url} target="_blank" rel="noreferrer" className="text-blue-600 shrink-0 pt-[2px]" title={f.source_title || f.source_url}>↗</a>
                : <span className="text-[10px] text-amber-700 shrink-0 pt-[2px]" title="нет источника">непроверено</span>}
              <button onClick={() => delFact.mutate(f.id)}
                className="text-ink-mute hover:text-red-600 opacity-0 group-hover:opacity-100 shrink-0 pt-[2px]">×</button>
            </li>
          );})}
        </ul>
      )}
      {open ? (
        <FactForm section={section} busy={addFact.isPending}
          onSubmit={(b) => addFact.mutate(b)} onCancel={() => setOpen(false)} />
      ) : (
        <button onClick={() => setOpen(true)}
          className="mt-1 text-[11px] px-2 py-0.5 rounded border border-dashed border-ink-line text-ink-mute hover:bg-slate-50">
          + факт
        </button>
      )}
    </section>
  );
}

function FactForm({ section, onSubmit, onCancel, busy }: {
  section: { keyPh: string; valPh: string };
  onSubmit: (b: Partial<EntityFact>) => void; onCancel: () => void; busy: boolean;
}) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [asOf, setAsOf] = useState("");
  const submit = () => {
    if (!value.trim()) return;
    onSubmit({ key: key.trim(), value: value.trim(), source_url: url.trim(),
      source_title: title.trim(), as_of: asOf.trim() || null, verified: !!url.trim() });
  };
  const inp = "text-xs border border-ink-line rounded px-2 py-1";
  return (
    <div className="mt-2 p-2 rounded bg-slate-50 border border-ink-line space-y-1.5">
      <div className="flex gap-1.5">
        <input className={`${inp} w-28`} placeholder={section.keyPh} value={key} onChange={e => setKey(e.target.value)} />
        <input className={`${inp} flex-1`} placeholder={`${section.valPh} *`} value={value} onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") submit(); }} autoFocus />
        <input className={`${inp} w-24`} placeholder="дата" value={asOf} onChange={e => setAsOf(e.target.value)} />
      </div>
      <div className="flex gap-1.5">
        <input className={`${inp} flex-1`} placeholder="ссылка-источник" value={url} onChange={e => setUrl(e.target.value)} />
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

function LinkForm({ onSubmit, onCancel, busy }: {
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
