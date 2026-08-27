import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { RunProgress, useElapsed } from "./RunProgress";
import { HintTarget } from "./Hint";
import type { Entity, EntityFact, Client, AboutProposal, AboutAutofillResult, FounderProposal, FounderDiscoverResult, MentionedCompany } from "../types";

interface Props {
  clientId: string;
}

const PANEL = "rounded-lg border border-ink-line bg-white p-5";
const FIELD = "text-sm border border-ink-line rounded-xl bg-white px-3 py-2 focus:outline-none focus:ring-1 focus:ring-ink focus:border-ink transition";
const FIELD_SM = "text-xs border border-ink-line rounded-xl bg-white px-3 py-2 focus:outline-none focus:ring-1 focus:ring-ink focus:border-ink transition";
const BUTTON_PRIMARY = "h-10 shrink-0 text-sm bg-ink text-white rounded-xl px-4 font-normal hover:opacity-90 disabled:opacity-40 transition";
const BUTTON_SECONDARY = "shrink-0 rounded-xl border border-ink-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-[#fbfbf7] disabled:opacity-40 transition";
const BUTTON_GHOST = "text-xs font-normal text-ink-mute hover:text-ink transition";
const BUTTON_DASHED = "shrink-0 rounded-xl border border-dashed border-ink-line bg-white px-3 py-1.5 text-xs font-medium text-ink-mute hover:bg-[#fbfbf7] hover:text-ink transition";
const EMPTY_NOTE = "rounded-xl border border-ink-line bg-[#fbfbf7] px-3 py-2 text-xs text-ink-mute";
const WARNING_NOTE = "rounded-xl border border-[#f0c86b]/70 bg-[#fff9ea] px-3 py-2 text-xs text-[#5b4215]";
const MODAL_PANEL = "bg-white rounded-lg border border-ink-line w-full max-w-2xl mx-4 p-5 space-y-3";
const CHIP = "inline-flex items-center gap-1 rounded-xl border border-ink-line bg-white px-2 py-1 text-[11px] leading-none text-ink hover:bg-[#fbfbf7] transition";
const CHIP_LINK = `${CHIP} text-flag-blue hover:text-flag-blue`;
const CHIP_DASHED = "inline-flex items-center gap-1 rounded-xl border border-dashed border-ink-line bg-white px-2 py-1 text-[11px] leading-none text-ink-mute hover:bg-[#fbfbf7] hover:text-ink transition";
const CHIP_SUGGESTION = "inline-flex items-center gap-1 rounded-xl border border-flag-blue/40 bg-white px-2 py-1 text-[11px] leading-none text-flag-blue hover:bg-flag-blue/5 disabled:opacity-50 transition";
const CHIP_IMPORT = "inline-flex items-center gap-1 rounded-xl border border-indigo-200 bg-white px-2 py-1 text-[11px] leading-none text-indigo-600 hover:bg-indigo-50 disabled:opacity-50 transition";
const CHIP_DANGER = "text-ink-mute hover:text-red-600 transition";

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

// читаемый домен из URL: https://www.accumulator.co/ → accumulator.co
function readableDomain(u: string): string {
  return (u || "").replace(/^https?:\/\//i, "").replace(/^www\./i, "").replace(/\/+$/, "");
}
// Ссылка-факт (секция sites) → {label, href}. Главный сайт показываем доменом
// (читаемо), href берём из ЗНАЧЕНИЯ (а не из source_url — source это провенанс).
function linkInfo(f: EntityFact): { label: string; href: string } {
  const v = (f.value || "").trim();
  const isUrl = /^https?:\/\//i.test(v);
  const isDomain = !isUrl && /^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(v) && !/\s/.test(v);
  const href = isUrl ? v : isDomain ? `https://${v}` : (f.source_url || "#");
  const k = (f.key || "").toLowerCase();
  let label: string;
  if (/linkedin/.test(k) || /linkedin\.com/i.test(href)) label = "LinkedIn";
  else if (/twitter|(^|_)x($|_)/.test(k) || /(twitter|x)\.com/i.test(href)) label = "X";
  else if (/github/.test(k) || /github\.com/i.test(href)) label = "GitHub";
  else if (/wiki/.test(k) || /wikipedia\.org/i.test(href)) label = "Wikipedia";
  else if (/news|blog|press/.test(k)) label = "News";
  else label = readableDomain(href) || "сайт";   // основной сайт → читаемый домен
  return { label, href };
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
  const mentioned = useQuery({ queryKey: ["mentioned-companies", clientId], queryFn: () => api.mentionedCompanies(clientId) });
  const inval = () => qc.invalidateQueries({ queryKey: ["entities", clientId] });

  const company = (entities.data ?? []).find(e => e.kind === "company") ?? null;
  const currentCompanyLogo = (mentioned.data ?? []).find(m => m.is_current)?.logo || "";

  const createCompany = useMutation({
    mutationFn: () => api.createEntity(clientId, { kind: "company", name: client.data?.name || clientId, confirmed: true }),
    onSuccess: inval,
  });

  if (entities.isLoading) return <div className="p-5 text-sm text-ink-mute">Загрузка…</div>;

  if (!company) {
    return (
      <div className="p-5 max-w-[820px] mx-auto space-y-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Профиль компании</h2>
          <p className="text-[13px] text-ink-mute mt-0.5">
            Соберите структурные бизнес-факты: описание, фаундеров, ссылки, раунды и метрики.
          </p>
        </div>
        <p className={EMPTY_NOTE}>
          Карточка компании ещё не создана. Создайте её, чтобы заполнить профиль.
        </p>
        <HintTarget
          title="Создать карточку компании"
          body="Создаёт структурный профиль компании: после этого можно будет добавить фаундеров, ссылки, раунды, метрики и другие бизнес-факты."
        >
          <button onClick={() => createCompany.mutate()} disabled={createCompany.isPending}
            className={BUTTON_PRIMARY}>
            {createCompany.isPending ? "Создаю…" : "Создать карточку компании"}
          </button>
        </HintTarget>
      </div>
    );
  }

  const bySection = (sid: string) => (company.facts || []).filter(f => (f.section || "") === sid);
  // ссылки секции «sites» переезжают в шапку как официальные ссылки
  const siteFacts = (company.facts || []).filter(f => (f.section || "") === "sites");
  const ungrouped = (company.facts || []).filter(f =>
    (f.section || "") !== "sites" && !SECTIONS.some(s => s.id === (f.section || "")));

  return (
    <div className="p-5 max-w-[820px] mx-auto space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Профиль компании</h2>
          <p className="text-[13px] text-ink-mute mt-0.5">
            Соберите структурные бизнес-факты: описание, фаундеров, ссылки, раунды и метрики.
          </p>
        </div>
        <Autofill clientId={clientId} onCommitted={inval} />
      </div>
      <CompanyHeader company={company} siteFacts={siteFacts} currentCompanyLogo={currentCompanyLogo}
        founders={(entities.data ?? []).filter(e => e.kind === "founder")} onChanged={inval} />
      <FoundersBlock clientId={clientId} founders={(entities.data ?? []).filter(e => e.kind === "founder")}
        candidates={founderCandidates(company.facts || [])} onChanged={inval} />
      <MentionedCompaniesBlock clientId={clientId} currentCompanyLogo={company.links?.logo || ""} />
      {/* одна широкая колонка — секции стопкой во всю ширину */}
      {SECTIONS.map(s => (
        <SectionBlock key={s.id} section={s} entityId={company.id} facts={bySection(s.id)} onChanged={inval} />
      ))}
      {ungrouped.length > 0 && (
        <SectionBlock section={{ id: "", label: "Прочее", hint: "факты без секции", keyPh: "ключ", valPh: "значение" }}
          entityId={company.id} facts={ungrouped} onChanged={inval} />
      )}
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
  const inp = FIELD_SM;
  const have = new Set(founders.map(f => (f.name || "").toLowerCase().trim()));
  const hints = candidates.filter(c => !have.has(c.name.toLowerCase().trim()));

  return (
    <section className={PANEL}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold">Фаундеры</h3>
          <p className="mt-0.5 text-xs text-ink-mute">К ним привязываются факты — кто именно говорит.</p>
        </div>
        <FounderDiscovery clientId={clientId} existing={founders} onChanged={onChanged} />
      </div>
      {hints.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-ink-mute">упомянуты в фактах:</span>
          {hints.map((c, i) => (
            <HintTarget
              key={i}
              title="Добавить фаундера из фактов"
              body={c.role ? `${c.name} · ${c.role}. Добавит этого человека в блок фаундеров компании.` : `${c.name}. Добавит этого человека в блок фаундеров компании.`}
            >
              <button onClick={() => addHint.mutate(c)} disabled={addHint.isPending}
                className={CHIP_SUGGESTION}>
                + {c.name}{c.role && <span className="text-ink-mute"> · {c.role}</span>}
              </button>
            </HintTarget>
          ))}
        </div>
      )}
      {founders.length === 0 ? (
        <div className={EMPTY_NOTE}>Фаундеры пока не добавлены. Можно найти их автоматически или добавить вручную.</div>
      ) : (
        <ul className="space-y-2 py-1">
          {founders.map(f => (
            <FounderRow key={f.id} clientId={clientId} f={f} onChanged={onChanged} onRemove={() => remove.mutate(f.id)} />
          ))}
        </ul>
      )}
      {adding ? (
        <div className="mt-2 flex flex-wrap gap-1.5 items-center">
          <input className={`${inp} w-40`} placeholder="имя фаундера *" value={name} onChange={e => setName(e.target.value)} autoFocus
            onKeyDown={e => { if (e.key === "Enter" && name.trim()) create.mutate(); }} />
          <input className={`${inp} w-36`} placeholder="роль (напр. CEO)" value={role} onChange={e => setRole(e.target.value)} />
          <HintTarget title="Добавить фаундера" body="Создаёт фаундера вручную и привязывает его к текущей компании.">
            <button onClick={() => create.mutate()} disabled={create.isPending || !name.trim()}
              className={BUTTON_SECONDARY}>{create.isPending ? "…" : "добавить"}</button>
          </HintTarget>
          <button onClick={() => setAdding(false)} className={BUTTON_GHOST}>отмена</button>
        </div>
      ) : (
        <HintTarget title="Добавить вручную" body="Открывает поля для ручного добавления фаундера, если автоматический поиск ничего не нашёл или данные нужно поправить самому.">
          <button onClick={() => setAdding(true)} className={BUTTON_DASHED}>+ фаундер вручную</button>
        </HintTarget>
      )}
    </section>
  );
}

// Строка фаундера: фото-аватар, имя·роль, кликабельные соцсети/проф-профили,
// кнопка «найти профили» (веб+LLM подбирают ссылки и фото к этому человеку).
function FounderRow({ clientId, f, onChanged, onRemove }: { clientId: string; f: Entity; onChanged: () => void; onRemove: () => void }) {
  const patch = useMutation({
    mutationFn: (links: Record<string, string>) => api.patchEntity(f.id, { links }),
    onSuccess: onChanged,
  });
  const find = useMutation({
    mutationFn: () => api.findFounderProfiles(clientId, f.name),
    onSuccess: (r) => {
      const merged: Record<string, string> = { ...(f.links || {}), ...r.links };
      if (r.photo) merged.photo = r.photo;
      if (Object.keys(r.links).length || r.photo) patch.mutate(merged);
    },
  });
  // тот же человек в других компаниях → предложить влить профиль (ссылки/роль/url/note)
  const sameElsewhere = useQuery({
    queryKey: ["founder-by-name", f.name, clientId],
    queryFn: () => api.foundersByName(f.name, clientId),
    enabled: !!f.name.trim(),
  });
  const importProfile = useMutation({
    mutationFn: (fromId: number) => api.importFounderProfile(f.id, fromId),
    onSuccess: onChanged,
  });
  const matches = sameElsewhere.data?.matches ?? [];

  const [imgBad, setImgBad] = useState(false);
  const links = f.links || {};
  const photo = links.photo;
  const chips = Object.entries(links).filter(([k]) => k.toLowerCase() !== "photo");
  const initials = f.name.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const busy = find.isPending || patch.isPending || importProfile.isPending;

  return (
    <li className="flex items-start gap-2.5 group">
      {photo && !imgBad
        ? <img src={photo} alt="" onError={() => setImgBad(true)} className="w-9 h-9 rounded-full object-cover shrink-0 border border-ink-line" />
        : <span className="w-9 h-9 rounded-full bg-slate-100 grid place-items-center text-[11px] font-medium text-ink-mute shrink-0">{initials || "—"}</span>}
      <div className="flex-1 min-w-0">
        <div className="text-sm leading-tight"><span className="font-medium">{f.name}</span>{f.role && <span className="text-xs text-ink-mute"> · {f.role}</span>}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {chips.length === 0 && <span className="text-[11px] text-ink-mute italic">профили не заданы</span>}
          {chips.map(([k, url]) => (
            <a key={k} href={url} target="_blank" rel="noreferrer"
              className={CHIP_LINK}>{k} ↗</a>
          ))}
          <HintTarget title="Найти профили" body="Ищет публичные профили фаундера в вебе и добавляет найденные ссылки и фото в карточку человека.">
            <button onClick={() => find.mutate()} disabled={busy}
              className={`${CHIP_DASHED} disabled:opacity-50`}>
              {busy ? "ищу профили…" : "найти профили"}
            </button>
          </HintTarget>
        </div>
        {matches.length > 0 && (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-ink-mute" title="тот же человек уже есть в этих компаниях">👤 тот же в:</span>
            {matches.map(m => (
              <HintTarget key={m.id} title="Влить профиль" body={`Перенесёт ссылки, роль и заметки этого человека из компании «${m.client_name}» в текущую карточку.`}>
                <button onClick={() => importProfile.mutate(m.id)} disabled={busy}
                  className={CHIP_IMPORT}>
                  {m.client_name} ↓
                </button>
              </HintTarget>
            ))}
          </div>
        )}
      </div>
      <HintTarget title="Удалить фаундера" body="Удаляет этого человека из списка фаундеров текущей компании. Факты в матрице не меняются.">
        <button onClick={onRemove}
          className={`${BUTTON_GHOST} hover:text-red-600 opacity-0 group-hover:opacity-100 shrink-0`}>удалить</button>
      </HintTarget>
    </li>
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
      <HintTarget title="Найти фаундеров" body="Запускает веб-поиск фаундеров и их публичных профилей. Перед добавлением результаты появятся на проверку.">
        <button onClick={() => run.mutate()} disabled={run.isPending}
          className={BUTTON_SECONDARY}>
          {run.isPending ? "Ищу…" : "Найти фаундеров"}
        </button>
      </HintTarget>

      {(run.isPending || result || run.isError) && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => { if (!run.isPending && !commit.isPending) { setResult(null); run.reset(); } }}>
          <div className={MODAL_PANEL} onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Найденные фаундеры — на проверку</h3>
              <button onClick={() => { setResult(null); run.reset(); }} className={BUTTON_GHOST}>✕</button>
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
                                  <a key={k} href={url} target="_blank" rel="noreferrer" className={CHIP_LINK}>{k} ↗</a>
                                ))}
                          </div>
                        </div>
                        {f.source_url && <a href={f.source_url} target="_blank" rel="noreferrer" className="text-flag-blue shrink-0 text-sm hover:underline" title="источник">↗</a>}
                      </label>
                    );
                  })}
                </div>
                <div className="flex gap-2 items-center pt-1">
                  <button
                    onClick={() => commit.mutate(founders.filter((_, i) => accepted.has(i)))}
                    disabled={commit.isPending || accepted.size === 0}
                    className={BUTTON_SECONDARY}>
                    {commit.isPending ? "Добавляю…" : `Добавить отмеченных (${accepted.size})`}
                  </button>
                  <button onClick={() => { setResult(null); run.reset(); }} className={BUTTON_GHOST}>отмена</button>
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
        <HintTarget title="Из документа" body="Открывает форму: вставьте текст документа и URL источника, чтобы извлечь из него бизнес-факты для профиля компании.">
          <button onClick={() => setDocOpen(true)} disabled={run.isPending}
            className={BUTTON_SECONDARY}>
            Из документа
          </button>
        </HintTarget>
        <HintTarget title="Авто-наполнить" body="Ищет и предлагает бизнес-факты для профиля по текущей матрице и веб-источникам. Ничего не сохраняет без вашей проверки.">
          <button onClick={() => run.mutate({ use_web: true })} disabled={run.isPending}
            className={BUTTON_SECONDARY}>
            {run.isPending ? "Ищу…" : "Авто-наполнить"}
          </button>
        </HintTarget>
      </div>

      {docOpen && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => setDocOpen(false)}>
          <div className={MODAL_PANEL} onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Из документа</h3>
              <button onClick={() => setDocOpen(false)} className={BUTTON_GHOST}>✕</button>
            </div>
            <p className="text-[11px] text-ink-mute">Вставь текст (deep-research отчёт, статья) и URL источника — факты будут привязаны к этой ссылке.</p>
            <input className={`w-full ${FIELD_SM}`} placeholder="URL источника * (https://…)" value={pUrl} onChange={e => setPUrl(e.target.value)} />
            <input className={`w-full ${FIELD_SM}`} placeholder="название источника (необязательно)" value={pTitle} onChange={e => setPTitle(e.target.value)} />
            <textarea className={`w-full h-48 ${FIELD_SM}`} placeholder="вставь текст документа *" value={pasted} onChange={e => setPasted(e.target.value)} />
            <div className="flex gap-2 items-center">
              <HintTarget title="Извлечь факты" body="Разберёт вставленный документ и покажет найденные бизнес-факты на проверку перед сохранением.">
                <button onClick={submitDoc} disabled={!pasted.trim() || !pUrl.trim()}
                  className={BUTTON_SECONDARY}>Извлечь факты</button>
              </HintTarget>
              <button onClick={() => setDocOpen(false)} className={BUTTON_GHOST}>отмена</button>
              {pasted.trim() && !pUrl.trim() && <span className="text-[10px] text-amber-700">нужен URL источника для привязки фактов</span>}
            </div>
          </div>
        </div>
      )}

      {(run.isPending || result || run.isError) && (
        <div className="fixed inset-0 z-30 bg-black/30 flex items-start justify-center overflow-y-auto py-10"
          onClick={() => { if (!run.isPending && !commit.isPending) { setResult(null); run.reset(); } }}>
          <div className={MODAL_PANEL} onClick={e => e.stopPropagation()}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">Авто-наполнение — предложения</h3>
              <button onClick={() => { setResult(null); run.reset(); }} className={BUTTON_GHOST}>✕</button>
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
                            <a href={p.source_url} target="_blank" rel="noreferrer" className="text-flag-blue shrink-0 hover:underline" title={p.source_title || p.source_url}>↗</a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2 items-center pt-1">
                  <HintTarget title="Внести отмеченные" body="Сохранит только выбранные предложения в профиль компании. Остальные предложения будут проигнорированы.">
                    <button
                      onClick={() => commit.mutate(proposals.filter((_, i) => accepted.has(i)))}
                      disabled={commit.isPending || accepted.size === 0}
                      className={BUTTON_SECONDARY}>
                      {commit.isPending ? "Вношу…" : `Внести отмеченные (${accepted.size})`}
                    </button>
                  </HintTarget>
                  <button onClick={() => { setResult(null); run.reset(); }} className={BUTTON_GHOST}>отмена</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

// Детерминированный цвет монограммы из имени (фавикон-стиль).
function monoColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360} 42% 42%)`;
}

// Логотип компании: кастомная картинка (links.logo) или авто-двухбуквенная монограмма.
function CompanyLogo({ company, logoFallback = "", onChanged }: { company: Entity; logoFallback?: string; onChanged: () => void }) {
  const savedLogo = company.links?.logo;
  const logo = savedLogo || logoFallback;
  const [imgBad, setImgBad] = useState(false);
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(logo || "");
  const save = useMutation({
    mutationFn: (u: string) => {
      const links = { ...(company.links || {}) };
      if (u) links.logo = u; else delete links.logo;
      return api.patchEntity(company.id, { links });
    },
    onSuccess: () => { setEditing(false); setImgBad(false); onChanged(); },
  });
  const initials = company.name.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "—";
  return (
    <div className="shrink-0 relative">
      {logo && !imgBad
        ? <img src={logo} alt="" onError={() => setImgBad(true)} className="w-11 h-11 rounded-lg object-cover border border-ink-line" />
        : <span className="w-11 h-11 rounded-lg grid place-items-center text-sm font-semibold text-white select-none"
            style={{ background: monoColor(company.name) }}>{initials}</span>}
      <HintTarget title="Изменить логотип" body="Откроет поле для ссылки на логотип компании. Если ссылку убрать, вернётся буквенная монограмма.">
        <button onClick={() => { setUrl(savedLogo || logoFallback || ""); setEditing(v => !v); }}
          className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-white border border-ink-line grid place-items-center text-[9px] font-normal text-ink-mute hover:text-ink transition">✎</button>
      </HintTarget>
      {editing && (
        <div className="absolute right-0 top-12 z-10 bg-white border border-ink-line rounded-lg shadow-lg p-3 w-64 space-y-2">
          <div className="text-[11px] text-ink-mute mb-1">Ссылка на логотип (пусто = буквенный):</div>
          <input autoFocus value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…/logo.png"
            className={`w-full ${FIELD_SM}`} />
          <div className="flex gap-2 mt-1.5 items-center">
            <HintTarget title="Сохранить логотип" body="Сохраняет ссылку на логотип в профиле компании.">
              <button onClick={() => save.mutate(url.trim())} disabled={save.isPending}
                className={BUTTON_SECONDARY}>сохранить</button>
            </HintTarget>
            {savedLogo && (
              <HintTarget title="Убрать логотип" body="Удаляет пользовательскую ссылку на логотип и возвращает буквенную монограмму.">
                <button onClick={() => save.mutate("")} className={`${BUTTON_GHOST} text-[11px] hover:text-red-600`}>убрать</button>
              </HintTarget>
            )}
            <button onClick={() => setEditing(false)} className={`${BUTTON_GHOST} ml-auto`}>отмена</button>
          </div>
        </div>
      )}
    </div>
  );
}

// Мини-аватар фаундера для шапки: фото или инициалы.
function FounderAvatar({ f }: { f: Entity }) {
  const [bad, setBad] = useState(false);
  const photo = (f.links || {}).photo;
  const initials = f.name.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "—";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-xl border border-ink-line bg-white pl-0.5 pr-2 py-0.5 text-xs"
      title={f.role ? `${f.name} · ${f.role}` : f.name}>
      {photo && !bad
        ? <img src={photo} alt="" onError={() => setBad(true)} className="w-5 h-5 rounded-full object-cover" />
        : <span className="w-5 h-5 rounded-full bg-slate-200 grid place-items-center text-[9px] font-medium text-ink-mute">{initials}</span>}
      <span className="text-ink">{f.name}</span>
    </span>
  );
}

// Блок «Упомянутые компании» — внешние компании (не клиенты) под этим клиентом.
function MentionedCompaniesBlock({ clientId, currentCompanyLogo = "" }: { clientId: string; currentCompanyLogo?: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["mentioned-companies", clientId], queryFn: () => api.mentionedCompanies(clientId) });
  const inval = () => qc.invalidateQueries({ queryKey: ["mentioned-companies", clientId] });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () => api.addMentionedCompany(clientId, { name: name.trim(), note: note.trim() }),
    onSuccess: () => { setAdding(false); setName(""); setNote(""); inval(); },
  });
  const del = useMutation({ mutationFn: (id: number) => api.deleteMentionedCompany(id), onSuccess: inval });
  const list = q.data ?? [];
  const inp = FIELD;
  return (
    <section className={PANEL}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold">Упомянутые компании</h3>
          <p className="mt-0.5 text-xs text-ink-mute">Компании, о которых говорим.</p>
        </div>
      </div>
      {list.length === 0 && !adding && (
        <div className={EMPTY_NOTE}>Упомянутых компаний пока нет. Добавьте внешнюю компанию, если она важна для контекста.</div>
      )}
      <div className="flex flex-wrap gap-2">
        {list.map(m => <MentionedCard key={m.id} m={m} currentCompanyLogo={currentCompanyLogo} onChanged={inval} onRemove={() => del.mutate(m.id)} />)}
      </div>
      {adding ? (
        <div className="mt-2 flex flex-wrap gap-2 items-center">
          <input className={`${inp} w-44`} placeholder="название *" value={name} onChange={e => setName(e.target.value)} autoFocus />
          <input className={`${inp} w-60`} placeholder="контекст (напр. прошлая компания фаундера)" value={note} onChange={e => setNote(e.target.value)} />
          <HintTarget title="Добавить компанию" body="Добавит внешнюю компанию в список упоминаний. Это не создаёт нового клиента и не меняет матрицу.">
            <button onClick={() => add.mutate()} disabled={!name.trim() || add.isPending}
              className={BUTTON_SECONDARY}>добавить</button>
          </HintTarget>
          <button onClick={() => setAdding(false)} className={BUTTON_GHOST}>отмена</button>
        </div>
      ) : (
        <HintTarget title="Добавить упомянутую компанию" body="Открывает форму для внешней компании: конкурента, прошлой компании фаундера, партнёра или другого важного контекста.">
          <button onClick={() => setAdding(true)} className={BUTTON_DASHED}>+ компания</button>
        </HintTarget>
      )}
    </section>
  );
}

function MentionedCard({ m, currentCompanyLogo = "", onChanged, onRemove }: { m: MentionedCompany; currentCompanyLogo?: string; onChanged: () => void; onRemove: () => void }) {
  const isCurrent = !!m.is_current;   // текущая компания: контекст/имя защищены, правится только логотип
  const effectiveLogo = m.logo || (isCurrent ? currentCompanyLogo : "");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(m.name);
  const [note, setNote] = useState(m.note || "");
  const [logo, setLogo] = useState(m.logo || "");
  const [imgBad, setImgBad] = useState(false);
  const save = useMutation({
    mutationFn: () => api.patchMentionedCompany(m.id,
      isCurrent ? { logo: logo.trim() }
                : { name: name.trim() || m.name, note: note.trim(), logo: logo.trim() }),
    onSuccess: () => { setEditing(false); setImgBad(false); onChanged(); },
  });
  const initials = m.name.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "—";
  const inp = `w-full ${FIELD_SM}`;
  return (
    <div className={`relative flex items-center gap-2 rounded-xl border px-2 py-1.5 group ${isCurrent ? "border-[#d8e6b8] bg-[#fbfff2]" : "border-ink-line bg-white"}`}>
      {effectiveLogo && !imgBad
        ? <img src={effectiveLogo} alt="" onError={() => setImgBad(true)} className="w-7 h-7 rounded object-cover shrink-0" />
        : <span className="w-7 h-7 rounded grid place-items-center text-[10px] font-semibold text-white select-none shrink-0"
            style={{ background: monoColor(m.name) }}>{initials}</span>}
      <div className="min-w-0">
        <div className="text-xs font-medium text-ink leading-tight flex items-center gap-1">
          <span className="truncate">{m.name}</span>
          {isCurrent && <span className="rounded-full bg-[#e6f4c6] px-1.5 py-px text-[8px] leading-none text-[#40551f] shrink-0">текущая</span>}
        </div>
        {m.note && <div className="text-[10px] text-ink-mute leading-tight truncate max-w-[13rem]">{m.note}</div>}
      </div>
      <HintTarget title={isCurrent ? "Изменить логотип" : "Править компанию"} body={isCurrent ? "Для текущей компании можно изменить только логотип." : "Открывает поля названия, контекста и логотипа этой упомянутой компании."}>
        <button onClick={() => { setName(m.name); setNote(m.note || ""); setLogo(m.logo || ""); setEditing(v => !v); }}
          className={`${BUTTON_GHOST} text-[10px] ml-1 text-ink-mute/50`}>✎</button>
      </HintTarget>
      {!isCurrent && (
        <HintTarget title="Убрать компанию" body="Удаляет эту компанию из списка упоминаний. Карточки фактов и данные клиента не меняются.">
          <button onClick={onRemove}
            className={`${BUTTON_GHOST} text-[13px] text-ink-mute/50 hover:text-red-600 opacity-0 group-hover:opacity-100`}>×</button>
        </HintTarget>
      )}
      {editing && (
        <div className="absolute left-0 top-11 z-10 bg-white border border-ink-line rounded-lg shadow-lg p-2.5 w-64 space-y-1.5">
          {!isCurrent ? (
            <>
              <div>
                <div className="text-[10px] text-ink-mute mb-0.5">Название (эксперты косячат — можно поправить):</div>
                <input autoFocus value={name} onChange={e => setName(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") save.mutate(); }} className={inp} />
              </div>
              <div>
                <div className="text-[10px] text-ink-mute mb-0.5">Контекст:</div>
                <input value={note} onChange={e => setNote(e.target.value)} placeholder="напр. прошлая компания фаундера" className={inp} />
              </div>
            </>
          ) : (
            <div className="text-[10px] text-ink-mute">Текущая компания клиента — правится только логотип.</div>
          )}
          <div>
            <div className="text-[10px] text-ink-mute mb-0.5">Логотип (ссылка, пусто = буквенный):</div>
            <input autoFocus={isCurrent} value={logo} onChange={e => setLogo(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") save.mutate(); }} placeholder="https://…/logo.png" className={inp} />
          </div>
          <div className="flex gap-2 items-center pt-0.5">
            <HintTarget title="Сохранить изменения" body="Сохраняет изменения названия, контекста или логотипа упомянутой компании.">
              <button onClick={() => save.mutate()} disabled={save.isPending || (!isCurrent && !name.trim())}
                className={BUTTON_SECONDARY}>сохранить</button>
            </HintTarget>
            <button onClick={() => setEditing(false)} className={`${BUTTON_GHOST} ml-auto`}>отмена</button>
          </div>
        </div>
      )}
    </div>
  );
}

function CompanyHeader({ company: e, siteFacts = [], founders = [], currentCompanyLogo = "", onChanged }: { company: Entity; siteFacts?: EntityFact[]; founders?: Entity[]; currentCompanyLogo?: string; onChanged: () => void }) {
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
  const hasAnyLink = Object.keys(e.links || {}).length > 0 || siteFacts.length > 0;
  const saveHead = useMutation({
    mutationFn: () => api.patchEntity(e.id, { name: name.trim() || e.name, role: role.trim(), note: note.trim() }),
    onSuccess: () => { setEditing(false); onChanged(); },
  });
  const inp = FIELD;

  if (editing) {
    return (
      <div className={`${PANEL} space-y-3`}>
        <div className="flex gap-2 flex-wrap">
          <input className={`${inp} w-48`} placeholder="название *" value={name} onChange={ev => setName(ev.target.value)} autoFocus />
          <input className={`${inp} w-48`} placeholder="роль / одной строкой" value={role} onChange={ev => setRole(ev.target.value)} />
        </div>
        <input className={`${inp} w-full`} placeholder="заметка (необязательно)" value={note} onChange={ev => setNote(ev.target.value)} />
        <div className="flex gap-2 items-center">
          <HintTarget title="Сохранить заголовок" body="Сохраняет название, короткую роль/описание и заметку в шапке профиля компании.">
            <button onClick={() => saveHead.mutate()} disabled={saveHead.isPending || !name.trim()}
              className={BUTTON_SECONDARY}>{saveHead.isPending ? "…" : "сохранить"}</button>
          </HintTarget>
          <button onClick={() => { setName(e.name); setRole(e.role || ""); setNote(e.note || ""); setEditing(false); }}
            className={BUTTON_GHOST}>отмена</button>
        </div>
      </div>
    );
  }

  return (
    <div className={`${PANEL} flex items-start gap-4`}>
      <div className="flex-1 min-w-0">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h2 className="text-lg font-semibold">{e.name}</h2>
        {e.role && <span className="text-sm text-ink-mute">· {e.role}</span>}
        <HintTarget title="Править заголовок" body="Открывает редактирование названия компании, короткого описания и заметки в шапке профиля.">
          <button onClick={() => setEditing(true)} className={BUTTON_GHOST}>✎</button>
        </HintTarget>
        <span className="ml-auto text-[11px] text-ink-mute">бизнес-профиль · без нарратива</span>
      </div>
      {e.note && <div className="mt-1 text-xs text-ink-mute">{e.note}</div>}
      {founders.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] uppercase tracking-wide text-ink-mute/80 mr-0.5">Фаундеры:</span>
          {founders.map(f => <FounderAvatar key={f.id} f={f} />)}
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-ink-mute/80 mr-0.5">Официальные ссылки:</span>
        {!hasAnyLink && <span className="text-[11px] text-ink-mute">ссылки пока не добавлены</span>}
        {/* ссылки-факты (секция sites) — читаемый домен, href из значения */}
        {siteFacts.map(f => {
          const { label, href } = linkInfo(f);
          return (
            <span key={`f${f.id}`} className={CHIP}>
              <a href={href} target="_blank" rel="noreferrer" className="text-flag-blue hover:underline" title={href}>{label}</a>
              <HintTarget title="Убрать ссылку" body="Удаляет эту ссылку из официальных ссылок профиля. Исходные факты в матрице не меняются.">
                <button onClick={() => delFact.mutate(f.id)} className={CHIP_DANGER}>×</button>
              </HintTarget>
            </span>
          );
        })}
        {/* ссылки entity.links */}
        {Object.entries(e.links || {}).map(([k, url]) => (
          <span key={k} className={CHIP}>
            <a href={url} target="_blank" rel="noreferrer" className="text-flag-blue hover:underline">{k}</a>
            <HintTarget title="Убрать ссылку" body="Удаляет эту пользовательскую ссылку из шапки профиля компании.">
              <button onClick={() => { const { [k]: _d, ...rest } = e.links || {}; setLinks.mutate(rest); }}
                className={CHIP_DANGER}>×</button>
            </HintTarget>
          </span>
        ))}
        <HintTarget title="Добавить ссылку" body="Открывает форму для официальной ссылки компании: сайт, LinkedIn, X, GitHub, Wikipedia или другой профиль.">
          <button onClick={() => setLinkOpen(v => !v)} className={CHIP_DASHED}>+ ссылка</button>
        </HintTarget>
      </div>
      {linkOpen && (
        <LinkForm busy={setLinks.isPending}
          onSubmit={(label, url) => setLinks.mutate({ ...(e.links || {}), [label]: url })}
          onCancel={() => setLinkOpen(false)} />
      )}
      </div>
      <CompanyLogo company={e} logoFallback={currentCompanyLogo} onChanged={onChanged} />
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
    <section className={PANEL}>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <h3 className="text-sm font-semibold">{section.label}</h3>
        <span className="text-[11px] text-ink-mute text-right">{section.hint}</span>
      </div>
      {facts.length === 0 ? (
        <div className={EMPTY_NOTE}>Фактов в этом разделе пока нет.</div>
      ) : (
        <ul className="space-y-1 py-1">
          {facts.map(f => {
            const label = humanizeKey(f.key);
            return (
            <li key={f.id} className="text-sm flex gap-2.5 group items-start">
              {label && <span className="shrink-0 w-24 text-[11px] uppercase tracking-wide text-ink-mute pt-[3px] leading-tight">{label}</span>}
              <span className="flex-1 min-w-0 leading-snug break-words">{f.value}{f.as_of && <span className="text-[11px] text-ink-mute"> · {f.as_of}</span>}</span>
              {f.source_url
                ? <a href={f.source_url} target="_blank" rel="noreferrer" className="text-flag-blue hover:underline shrink-0 pt-[2px]" title={f.source_title || f.source_url}>↗</a>
                : <span className="text-[10px] text-amber-700 shrink-0 pt-[2px]" title="нет источника">непроверено</span>}
              <HintTarget title="Удалить факт" body="Удаляет этот факт из структурного профиля компании. Матрица знаний не меняется.">
                <button onClick={() => delFact.mutate(f.id)}
                  className={`${BUTTON_GHOST} hover:text-red-600 opacity-0 group-hover:opacity-100 shrink-0 pt-[2px]`}>×</button>
              </HintTarget>
            </li>
          );})}
        </ul>
      )}
      {open ? (
        <FactForm section={section} busy={addFact.isPending}
          onSubmit={(b) => addFact.mutate(b)} onCancel={() => setOpen(false)} />
      ) : (
        <HintTarget title="Добавить факт" body="Открывает форму ручного добавления факта в этот раздел профиля компании.">
          <button onClick={() => setOpen(true)} className={BUTTON_DASHED}>
            + факт
          </button>
        </HintTarget>
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
  const inp = FIELD_SM;
  return (
    <div className="mt-3 rounded-2xl bg-[#fbfbf7] border border-ink-line p-3 space-y-3">
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
        <HintTarget title="Добавить факт" body="Сохраняет заполненный факт в текущий раздел профиля. Если указана ссылка, факт будет помечен как проверенный источником.">
          <button onClick={submit} disabled={busy || !value.trim()}
            className={BUTTON_SECONDARY}>{busy ? "…" : "добавить"}</button>
        </HintTarget>
        <button onClick={onCancel} className={BUTTON_GHOST}>отмена</button>
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
  const inp = FIELD_SM;
  return (
    <div className="mt-1.5 flex gap-1.5 items-center">
      <input className={`${inp} w-24`} placeholder="Wiki / News / X" value={label} onChange={e => setLabel(e.target.value)} autoFocus />
      <input className={`${inp} flex-1`} placeholder="https://…" value={url} onChange={e => setUrl(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") submit(); }} />
      <HintTarget title="Сохранить ссылку" body="Добавляет ссылку в шапку профиля компании с указанной подписью.">
        <button onClick={submit} disabled={busy || !label.trim() || !url.trim()}
          className={BUTTON_SECONDARY}>ок</button>
      </HintTarget>
      <button onClick={onCancel} className={BUTTON_GHOST}>×</button>
    </div>
  );
}
