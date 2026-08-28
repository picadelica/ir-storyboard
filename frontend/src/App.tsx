import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Navigate, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "./api";
import type { CellSummary, Layer } from "./types";
import Sidebar from "./components/Sidebar";
import UserMenu from "./components/UserMenu";
import MatrixGrid from "./components/MatrixGrid";
import CompanyAbout from "./components/CompanyAbout";
import CellDrawer from "./components/CellDrawer";
import CycleRunner from "./components/CycleRunner";
import ArtifactsView from "./components/ArtifactsView";
import PunchListView from "./components/PunchListView";
import InterviewView from "./components/InterviewView";
import ScorecardView from "./components/ScorecardView";
import FactAuditView from "./components/FactAuditView";
import WorkView from "./components/WorkView";
import ResearchView from "./components/ResearchView";
import MonitoringView from "./components/MonitoringView";
import AddDataHub from "./components/AddDataHub";
import IngestLLMReport from "./components/IngestLLMReport";
import IngestYouTube from "./components/IngestYouTube";
import IngestAudio from "./components/IngestAudio";
import IngestClientFacts from "./components/IngestClientFacts";
import MethodologyView from "./components/MethodologyView";
import UsersView from "./components/UsersView";
import AdminView from "./components/AdminView";
import SearchBox from "./components/SearchBox";
import PlanView from "./components/PlanView";
import BriefComposer from "./components/BriefComposer";
import ExportView from "./components/ExportView";
import DossierView from "./components/DossierView";
import { HintTarget } from "./components/Hint";

const BUTTON_SECONDARY = "shrink-0 rounded-xl border border-ink-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-[#fbfbf7] disabled:opacity-40 transition";
const BUTTON_BLUE = "shrink-0 rounded-xl border border-flag-blue/40 bg-white px-3 py-1.5 text-xs font-medium text-flag-blue hover:bg-flag-blue/5 disabled:opacity-40 transition";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/clients/:clientId/:tab?" element={<ClientPage />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  );
}

function RootRedirect() {
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients() });
  if (clients.isLoading) return <div className="p-8 text-sm text-ink-mute">Загрузка…</div>;
  if (clients.data && clients.data.length > 0)
    return <Navigate to={`/clients/${clients.data[0].id}/matrix`} replace />;
  return <EmptyState />;
}

function EmptyState() {
  return (
    <div className="h-screen flex">
      <Sidebar />
      <div className="flex-1 flex items-center justify-center text-sm text-ink-mute">
        <div className="max-w-sm text-center">
          <div className="text-base font-semibold text-ink mb-1">Клиентов пока нет</div>
          <div>Используйте кнопку в боковой панели, чтобы загрузить пилотный набор Accumulator.</div>
        </div>
      </div>
    </div>
  );
}

function ClientPage() {
  const { clientId, tab } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const activeTab = tab ?? "matrix";

  const [quarter, setQuarter] = useState("2026Q2");
  const [selectedSid, setSelectedSid] = useState<string | undefined>(sp.get("cell") ?? undefined);
  const [focusFactId, setFocusFactId] = useState<number | undefined>(
    sp.get("fact") ? Number(sp.get("fact")) : undefined);
  const [cycleKind, setCycleKind] = useState<"weekly" | "event" | "quarterly" | null>(null);
  const [pickedArtifactId, setPickedArtifactId] = useState<number | undefined>();
  const [present, setPresent] = useState(false);

  const layers = useQuery<Layer[]>({ queryKey: ["layers"], queryFn: api.layers });

  // Приход из поиска: ?cell=<sid>&fact=<id> → открыть ячейку, подсветить карточку,
  // затем убрать query, чтобы повторный выбор той же ячейки снова срабатывал.
  const cellParam = sp.get("cell");
  const factParam = sp.get("fact");
  useEffect(() => {
    if (!cellParam && !factParam) return;
    if (cellParam) setSelectedSid(cellParam);
    setFocusFactId(factParam ? Number(factParam) : undefined);
    const next = new URLSearchParams(sp);
    next.delete("cell"); next.delete("fact");
    setSp(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cellParam, factParam]);

  const onJumpToCell = (sid: string) => {
    nav(`/clients/${clientId}/matrix`);
    setSelectedSid(sid);
  };

  const toggleSelectedCell = (sid: string) => {
    setFocusFactId(undefined);
    setSelectedSid(current => current === sid ? undefined : sid);
  };

  return (
    <div className="h-screen flex">
      {!present && <Sidebar clientId={clientId} />}

      <main className="flex-1 flex flex-col overflow-hidden"
        style={{ transition: "margin-right 200ms", marginRight: selectedSid && (activeTab === "matrix" || activeTab === "scorecard" || activeTab === "audit") ? "28rem" : 0 }}>
        {present ? (
          <PresentBar clientId={clientId!} quarter={quarter} onExit={() => setPresent(false)} />
        ) : (
          <Tabs
            clientId={clientId!}
            activeTab={activeTab}
            quarter={quarter}
            onQuarterChange={setQuarter}
            onRunCycle={(k) => setCycleKind(k)}
            onTogglePresent={setPresent}
          />
        )}

        <div className="ir-workspace-scroll flex-1 min-h-0 overflow-y-auto">
          {activeTab === "about" && <CompanyAbout clientId={clientId!} />}
          {activeTab === "dossier" && <DossierView clientId={clientId!} />}
          {activeTab === "matrix" && (
            <MatrixGrid
              clientId={clientId!}
              selectedSubsectionId={selectedSid}
              onSelectCell={toggleSelectedCell}
              present={present}
            />
          )}
          {activeTab === "punch" && (
            <PunchListView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "interview" && (
            <InterviewView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "audit" && (
            <FactAuditView
              clientId={clientId!}
              onJumpToCell={onJumpToCell}
              selectedSubsectionId={selectedSid}
              onSelectCell={toggleSelectedCell}
            />
          )}
          {activeTab === "scorecard" && <ScorecardView clientId={clientId!} onSelectCell={toggleSelectedCell} />}
          {activeTab === "artifacts" && (
            <ArtifactsView clientId={clientId!} pickedArtifactId={pickedArtifactId} />
          )}
          {activeTab === "work" && (
            <WorkView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "research" && (
            <ResearchView clientId={clientId!} />
          )}
          {activeTab === "monitoring" && (
            <MonitoringView key={clientId} clientId={clientId!} />
          )}
          {activeTab === "ingest" && (
            <AddDataHub clientId={clientId!} layers={layers.data} />
          )}
          {activeTab === "source-file" && (
            <IngestLLMReport clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "youtube" && (
            <IngestYouTube clientId={clientId!} onJumpToCell={onJumpToCell} layers={layers.data} />
          )}
          {activeTab === "audio" && (
            <IngestAudio key={clientId} clientId={clientId!} onJumpToCell={onJumpToCell} layers={layers.data} />
          )}
          {activeTab === "client-facts" && (
            <IngestClientFacts key={clientId} clientId={clientId!} onJumpToCell={onJumpToCell} layers={layers.data} />
          )}
          {activeTab === "methodology" && (
            <MethodologyView key={clientId} clientId={clientId!} />
          )}
          {activeTab === "users" && <UsersView />}
          {activeTab === "admin" && <AdminView />}
          {activeTab === "plan" && (
            <PlanView clientId={clientId!} quarter={quarter} layers={layers.data} />
          )}
          {activeTab === "brief" && (
            <BriefComposer clientId={clientId!} layers={layers.data} />
          )}
          {activeTab === "export" && (
            <ExportView clientId={clientId!} />
          )}
        </div>

        {present && <PresentFooter clientId={clientId!} />}
      </main>

      {selectedSid && (activeTab === "matrix" || activeTab === "scorecard" || activeTab === "audit") && (
        <CellDrawer
          clientId={clientId!}
          subsectionId={selectedSid}
          focusFactId={focusFactId}
          auditFocus={activeTab === "audit" ? "all" : undefined}
          onClose={() => { setSelectedSid(undefined); setFocusFactId(undefined); }}
          layers={layers.data}
        />
      )}

      {cycleKind && (
        <CycleRunner
          clientId={clientId!}
          quarter={quarter}
          kind={cycleKind}
          onClose={() => setCycleKind(null)}
          onArtifactCreated={(aid) => {
            setCycleKind(null);
            setPickedArtifactId(aid);
            nav(`/clients/${clientId}/artifacts`);
          }}
        />
      )}
    </div>
  );
}

interface TabsProps {
  clientId: string;
  activeTab: string;
  quarter: string;
  onQuarterChange: (q: string) => void;
  onRunCycle: (kind: "weekly" | "event" | "quarterly") => void;
  onTogglePresent: (v: boolean) => void;
}

function ZoneIcon({ id }: { id: string }) {
  const p = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (id) {
    case "dossier":
      return <svg {...p}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5.5" /><circle cx="12" cy="12" r="1.8" /></svg>;
    case "map":
      return <svg {...p}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 4v16M4 9h16" /></svg>;
    case "about":
      return <svg {...p}><path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-5h6v5M9 11h.01M15 11h.01" /></svg>;
    case "build":
      return <svg {...p}><path d="M12 3l8 4.5-8 4.5-8-4.5z" /><path d="M4 12l8 4.5 8-4.5" /></svg>;
    case "health":
      return <svg {...p}><path d="M3 12h4l2 6 4-14 2 8h6" /></svg>;
    case "deliver":
      return <svg {...p}><path d="M21 16V8l-9-5-9 5v8l9 5z" /><path d="M3.5 7.5l8.5 5 8.5-5M12 12.5V22" /></svg>;
    case "work":
      return <svg {...p}><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></svg>;
    default:
      return null;
  }
}

type Sub = { id: string; label: string; hidden?: boolean };
const ZONES: { id: string; label: string; tabs: Sub[] }[] = [
  // Досье + About объединены в одну зону «Компания» (обзор + структурный профиль)
  { id: "dossier", label: "Компания", tabs: [{ id: "dossier", label: "Досье" }, { id: "about", label: "Профиль" }] },
  {
    id: "build", label: "Сбор данных", tabs: [
      { id: "ingest", label: "Добавить" },
      { id: "research", label: "Найти", hidden: true },
      { id: "monitoring", label: "Мониторинг" },
      { id: "source-file", label: "Файл / текст", hidden: true },
      { id: "youtube", label: "Видео", hidden: true },
      { id: "audio", label: "Аудио", hidden: true },
      { id: "client-facts", label: "От клиента", hidden: true },
    ],
  },
  { id: "map", label: "Факты", tabs: [{ id: "matrix", label: "Матрица" }] },
  {
    id: "health", label: "Проверка", tabs: [
      { id: "audit", label: "Проверка" },
    ],
  },
  {
    id: "deliver", label: "Итоги", tabs: [
      { id: "brief", label: "Бриф" },
      { id: "export", label: "Выгрузка" },
      { id: "artifacts", label: "Артефакты" },
      { id: "plan", label: "План" },
    ],
  },
  { id: "work", label: "Работа", tabs: [{ id: "work", label: "Работа" }] },
];

const ZONE_WIDTH: Record<string, string> = {
  dossier: "w-[104px]",
  map: "w-[96px]",
  build: "w-[120px]",
  health: "w-[104px]",
  work: "w-[92px]",
  deliver: "w-[104px]",
};

const ZONE_WIDTH_PX: Record<string, number> = {
  dossier: 104,
  map: 96,
  build: 120,
  health: 104,
  work: 92,
  deliver: 104,
};

const ZONE_HINTS: Record<string, string> = {
  dossier: "Бывший Dossier / About\nЗдесь вы смотрите общую картину по компании: досье, профиль, контекст и базовые сведения.",
  map: "Бывший Map / Matrix\nЗдесь вы анализируете матрицу знаний: видите заполненность разделов и открываете ячейки с фактами.",
  build: "Бывший Build / Ingest / Work\nЗдесь вы добавляете и обрабатываете источники: отчёты, видео, аудио, клиентские факты и исследования.",
  health: "Бывший Health\nЗдесь вы проверяете качество базы: пробелы, спорные факты, задачи и вопросы для интервью.",
  work: "Временная рабочая зона\nКанбан задач пока вынесен отдельно: посмотрим, стоит ли потом вернуть его в Проверку или спрятать глубже.",
  deliver: "Бывший Deliver\nЗдесь лежат итоговые материалы: брифы, планы, артефакты и выгрузки для дальнейшей работы.",
};

const TAB_HINTS: Record<string, string> = {
  dossier: "Консолидированное досье: общий синтез, карта знаний и ключевые блоки по компании.",
  about: "Структурный профиль компании: описание, фаундеры, ссылки и базовые факты.",
  ingest: "Единый вход для добавления данных: ссылка, файл, текст, аудио/видео; здесь выбирается и статус «от клиента».",
  "source-file": "Загрузка и разбор файлов, LLM-отчётов или больших текстовых материалов.",
  youtube: "Загрузка видео: транскрипт, извлечение фактов и запись в матрицу.",
  audio: "Загрузка аудио: транскрипт, факты, таймкоды и проверка перед записью.",
  "client-facts": "Факты от клиента: ручной ввод или документ, который нужно разложить по матрице.",
  research: "Поиск источников: запросы, найденные материалы, кандидаты фактов и импорт.",
  monitoring: "Мониторинг внешних сигналов и регулярная проверка изменений.",
  work: "Рабочая доска задач по источникам, пробелам и углублению.",
  brief: "Сборка брифа и нарратива из проверенной матрицы.",
  export: "Выгрузка матрицы и карточек в JSON/формат для передачи дальше.",
  artifacts: "Сохранённые материалы и документы, собранные из базы.",
  plan: "План действий и треки работы по выбранному периоду.",
};

function Tabs({ clientId, activeTab, quarter, onQuarterChange, onRunCycle, onTogglePresent }: TabsProps) {
  const nav = useNavigate();
  const activeZone = ZONES.find(z => z.tabs.some(t => t.id === activeTab)) ?? ZONES[0];
  const activeSub = activeZone.tabs.find(t => t.id === activeTab);
  const activeVisibleTabId = activeSub?.hidden ? activeZone.tabs.find(t => !t.hidden)?.id : activeTab;
  const showSub = activeZone.tabs.length > 1 || activeZone.id === "deliver";
  const zoneGapPx = 8;
  const activeZoneIndex = Math.max(0, ZONES.findIndex(z => z.id === activeZone.id));
  const activeZoneOffset = ZONES
    .slice(0, activeZoneIndex)
    .reduce((sum, z) => sum + ZONE_WIDTH_PX[z.id] + zoneGapPx, 0);
  const activeZoneMuted = activeZone.id === "work" || activeZone.id === "deliver";
  const zoneNavRef = useRef<HTMLDivElement | null>(null);
  const zonePillRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const fallbackCapsule = {
    left: activeZoneOffset,
    top: 0,
    width: ZONE_WIDTH_PX[activeZone.id],
    height: 30,
  };
  const [zoneCapsule, setZoneCapsule] = useState<typeof fallbackCapsule | null>(null);
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  // «Пользователи» видят супер-админ и владелец данных этой компании
  const canSeeUsers = !!me.data?.is_admin
    || (me.data?.tid != null && client.data?.owner_tid === me.data.tid);

  useLayoutEffect(() => {
    const measure = () => {
      const wrap = zoneNavRef.current;
      const pill = zonePillRefs.current[activeZone.id];
      if (!wrap || !pill) return;
      const wrapRect = wrap.getBoundingClientRect();
      const pillRect = pill.getBoundingClientRect();
      setZoneCapsule({
        left: pillRect.left - wrapRect.left,
        top: pillRect.top - wrapRect.top,
        width: pillRect.width,
        height: pillRect.height,
      });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [activeZone.id]);

  return (
    <div className="border-b border-ink-line bg-white/95 backdrop-blur">
      {/* одна строка: зоны · айдентика компании (приоритет) · глобальные действия */}
      <div className="flex items-center gap-2 px-4 py-2.5">
        <div ref={zoneNavRef} className="relative flex items-center gap-2">
          <span
            className={`pointer-events-none absolute left-0 top-0 rounded-full border shadow-sm transition-[transform,width,height,background-color,border-color] duration-300 ease-out
              ${activeZoneMuted ? "bg-[#f7f7f4] border-[#e2e3dc]" : "bg-[#f0fadb] border-[#cbd8a2]"}`}
            style={{
              width: zoneCapsule?.width ?? fallbackCapsule.width,
              height: zoneCapsule?.height ?? fallbackCapsule.height,
              transform: `translate3d(${zoneCapsule?.left ?? fallbackCapsule.left}px, ${zoneCapsule?.top ?? fallbackCapsule.top}px, 0)`,
            }}
          />
          {ZONES.map(z => {
            const active = z.id === activeZone.id;
            const muted = z.id === "work" || z.id === "deliver";
            return (
              <HintTarget key={z.id} title={z.label} body={ZONE_HINTS[z.id]}>
                <button
                  onClick={() => nav(`/clients/${clientId}/${z.tabs[0].id}`)}
                  className={`relative z-10 flex justify-center px-0.5 py-0 text-[12px] transition shrink-0 ${ZONE_WIDTH[z.id]}
                    ${active ? (muted ? "text-[#8b8d85]" : "text-[#40551f]") : muted ? "text-[#bbbdb5] hover:text-[#8b8d85]" : "text-ink-mute hover:text-ink"}`}
                >
                  <span
                    ref={(node) => { zonePillRefs.current[z.id] = node; }}
                    className={`relative flex items-center justify-center gap-1.5 rounded-full border border-transparent px-3 py-1.5 transition-colors
                      ${active ? "" : muted ? "hover:bg-[#f7f7f4]" : "hover:bg-[#f6f6f1]"}`}
                  >
                    <span className="w-3.5 h-3.5 shrink-0 grid place-items-center"><ZoneIcon id={z.id} /></span>
                    <span className="relative whitespace-nowrap">
                      <span className="invisible font-semibold">{z.label}</span>
                      <span className={`absolute inset-0 ${active ? "font-semibold" : "font-normal"}`}>{z.label}</span>
                    </span>
                    <span className={`absolute left-3 right-3 -bottom-[10px] h-[2.5px] rounded-full transition-opacity ${active ? (muted ? "bg-[#d2d4cc] opacity-100" : "bg-[#98c61b] opacity-100") : "opacity-0"}`} />
                  </span>
                </button>
              </HintTarget>
            );
          })}
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2 shrink-0">
          <SearchBox clientId={clientId} />
          <HintTarget title="Методология" body="Справочник структуры матрицы: описания ячеек, правила классификации и локальные заметки клиента.">
            <button
              onClick={() => nav(`/clients/${clientId}/methodology`)}
              className={`text-[12px] px-2.5 py-1.5 rounded-xl transition ${activeTab === "methodology" ? "bg-[#f6f6f1] text-ink font-semibold" : "text-ink-mute hover:text-ink hover:bg-[#f6f6f1]"}`}
            >Методология</button>
          </HintTarget>
          <div className="flex items-center rounded-xl border border-ink-line overflow-hidden text-xs bg-[#f6f6f1]">
            <HintTarget title="Режим аналитика" body="Обычный рабочий режим: редактирование, проверка, загрузка данных и навигация по интерфейсу.">
              <button className="px-3 py-1.5 bg-[#20221f] text-white font-semibold">Аналитик</button>
            </HintTarget>
            <HintTarget title="Презентация" body="Сфокусированный режим показа без лишней рабочей навигации.">
              <button
                onClick={() => onTogglePresent(true)}
                className="px-3 py-1.5 text-ink-mute hover:text-ink hover:bg-white transition"
              >Презентация</button>
            </HintTarget>
          </div>
          <UserMenu clientId={clientId} canSeeUsers={canSeeUsers} />
        </div>
      </div>

      {/* sub-tab row (hidden in present mode) */}
      {showSub && (
        <div className="border-t border-ink-line/60 bg-[#fbfbf7]">
          <div className="max-w-[820px] mx-auto flex items-center gap-1.5">
            {activeZone.tabs.filter(t => !t.hidden).map(t => (
              <HintTarget key={t.id} title={t.label} body={TAB_HINTS[t.id]}>
                <NavLink
                  to={`/clients/${clientId}/${t.id}`}
                  className={`px-5 py-2.5 text-[13px] border-b-[3px] transition whitespace-nowrap
                    ${activeVisibleTabId === t.id
                      ? "border-[#98c61b] text-ink font-semibold"
                      : "border-transparent text-ink-mute hover:text-ink hover:bg-white/70"}`}
                >
                  {t.label}
                </NavLink>
              </HintTarget>
            ))}

            {activeZone.id === "build" && <BuildActions clientId={clientId} />}

            {activeZone.id === "deliver" && (
              <div className="ml-auto flex items-center gap-1.5 py-1.5">
                <HintTarget title="Квартал" body="Период, к которому привязываются циклы, план и часть материалов. Например: 2026Q2.">
                  <input
                    value={quarter}
                    onChange={e => onQuarterChange(e.target.value)}
                    placeholder="2026Q2"
                    className="w-20 text-xs border border-ink-line rounded-xl px-2 py-1.5 font-mono"
                  />
                </HintTarget>
                <span className="text-[11px] text-ink-mute pl-1">Запустить цикл:</span>
                <HintTarget title="Недельный цикл" body="Собрать регулярные задачи и обновления на ближайшую неделю.">
                  <button onClick={() => onRunCycle("weekly")} className="text-xs px-3 py-1.5 rounded-xl border border-ink-line text-ink hover:bg-white">Недельный</button>
                </HintTarget>
                <HintTarget title="Событийный цикл" body="Запустить цикл от конкретного события: новости, встречи, изменения контекста.">
                  <button onClick={() => onRunCycle("event")} className="text-xs px-3 py-1.5 rounded-xl border border-ink-line text-ink hover:bg-white">Событийный</button>
                </HintTarget>
                <HintTarget title="Квартальный цикл" body="Собрать план и работу на квартальный горизонт.">
                  <button onClick={() => onRunCycle("quarterly")} className="text-xs px-3 py-1.5 rounded-xl border border-ink-line text-ink hover:bg-white">Квартальный</button>
                </HintTarget>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Действия уровня матрицы вынесены сюда (в зону Build), чтобы шапка матрицы была пустой
function BuildActions({ clientId }: { clientId: string }) {
  const qc = useQueryClient();
  const cells = useQuery<CellSummary[]>({ queryKey: ["matrix", clientId], queryFn: () => api.matrixView(clientId) });
  const totalMust = (cells.data ?? []).reduce((n, c) => n + (c.n_must || 0), 0);
  const genTitles = useMutation({
    mutationFn: () => api.generateTitles(clientId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["facts", clientId] }); },
  });
  return (
    <div className="ml-auto flex items-center gap-1.5 py-1.5">
      <HintTarget
        title="Заголовки карточек"
        body="Автоматически создаёт короткие названия для карточек фактов без заголовков. Удобно перед просмотром матрицы и выгрузкой материалов."
      >
        <button
          onClick={() => genTitles.mutate()}
          disabled={genTitles.isPending}
          className={`${BUTTON_SECONDARY} whitespace-nowrap`}
        >
          {genTitles.isPending ? "Генерирую заголовки…"
            : genTitles.isSuccess ? `Готово: ${genTitles.data?.titled ?? 0} заголовков`
            : "Заголовки карточек"}
        </button>
      </HintTarget>
      {totalMust > 0 && (
        <HintTarget
          title="Выгрузить обязательные"
          body="Скачивает must-have факты со звёздочкой нумерованным списком. Это удобно для согласования обязательных тезисов с клиентом."
        >
          <button
            onClick={() => api.downloadMustHaveFacts(clientId, clientId).catch(() => {})}
            className={`${BUTTON_BLUE} whitespace-nowrap`}
          >
            Выгрузить обязательные (★{totalMust})
          </button>
        </HintTarget>
      )}
    </div>
  );
}

function PresentFooter({ clientId }: { clientId: string }) {
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const name = client.data?.name ?? clientId;
  const analyst = me.data?.auth ? me.data.name : null;
  return (
    <div className="flex items-center justify-between border-t border-ink-line bg-white px-6 py-2.5 text-[11px] text-ink-mute">
      <span>Конфиденциально · {name} · отношения с инвесторами</span>
      <span className="flex items-center gap-2.5">
        {analyst && <span>Аналитик: {analyst}</span>}
        <span className="px-2 py-0.5 rounded-md bg-ink text-white text-[10px] tracking-wide">ЭФИР</span>
      </span>
    </div>
  );
}

function PresentBar({ clientId, quarter, onExit }: { clientId: string; quarter: string; onExit: () => void }) {
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const cells = useQuery<CellSummary[]>({ queryKey: ["matrix", clientId], queryFn: () => api.matrixView(clientId) });

  const name = client.data?.name ?? clientId;
  const sector = client.data?.sector;
  const mono = name.split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();

  const list = cells.data ?? [];
  const total = list.length;
  const covered = list.filter(c => (c.n_green || 0) > 0).length;
  const gaps = list.filter(c => (c.n_green || 0) === 0).length;
  const pct = total ? Math.round((covered / total) * 100) : 0;

  return (
    <div className="flex items-center justify-between border-b border-ink-line bg-white px-6 py-4">
      <div className="flex items-center gap-3.5">
        <span className="w-11 h-11 rounded-xl bg-ink/[0.06] flex items-center justify-center text-sm font-semibold text-ink select-none">{mono}</span>
        <div>
          <div className="text-xl font-semibold leading-tight tracking-tight text-ink">{name}</div>
          {sector && (
            <span className="inline-block mt-1 text-[11px] text-ink-mute bg-ink/[0.05] px-2 py-0.5 rounded-md">{sector}</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="text-right">
          <div className="text-lg font-semibold text-ink tabular-nums">{pct}% <span className="text-ink-mute font-normal">заполнено</span></div>
          <div className="text-xs text-ink-mute tabular-nums">{gaps} пробелов · {quarter}</div>
        </div>
        <div className="flex items-center rounded-lg border border-ink-line overflow-hidden text-xs">
          <button onClick={onExit} className="px-3 py-1.5 text-ink-mute hover:text-ink transition">Аналитик</button>
          <button className="px-3 py-1.5 bg-ink text-white">Презентация</button>
        </div>
      </div>
    </div>
  );
}
