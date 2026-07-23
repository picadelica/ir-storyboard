import { useEffect, useState } from "react";
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
import IngestLLMReport from "./components/IngestLLMReport";
import IngestYouTube from "./components/IngestYouTube";
import IngestAudio from "./components/IngestAudio";
import IngestClientFacts from "./components/IngestClientFacts";
import MethodologyView from "./components/MethodologyView";
import UsersView from "./components/UsersView";
import SearchBox from "./components/SearchBox";
import PlanView from "./components/PlanView";
import BriefComposer from "./components/BriefComposer";
import ExportView from "./components/ExportView";
import DossierView from "./components/DossierView";

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
  if (clients.isLoading) return <div className="p-8 text-sm text-ink-mute">Loading…</div>;
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
          <div className="text-base font-semibold text-ink mb-1">No clients yet</div>
          <div>Use the sidebar button to load the Accumulator pilot dataset.</div>
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

  return (
    <div className="h-screen flex">
      {!present && <Sidebar clientId={clientId} />}

      <main className="flex-1 flex flex-col overflow-hidden"
        style={{ transition: "margin-right 200ms", marginRight: selectedSid && (activeTab === "matrix" || activeTab === "scorecard") ? "28rem" : 0 }}>
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

        <div className="flex-1 overflow-y-auto">
          {activeTab === "about" && <CompanyAbout clientId={clientId!} />}
          {activeTab === "dossier" && <DossierView clientId={clientId!} />}
          {activeTab === "matrix" && (
            <MatrixGrid
              clientId={clientId!}
              selectedSubsectionId={selectedSid}
              onSelectCell={setSelectedSid}
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
            <FactAuditView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "scorecard" && <ScorecardView clientId={clientId!} onSelectCell={setSelectedSid} />}
          {activeTab === "artifacts" && (
            <ArtifactsView clientId={clientId!} pickedArtifactId={pickedArtifactId} />
          )}
          {activeTab === "work" && (
            <WorkView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "research" && (
            <ResearchView clientId={clientId!} />
          )}
          {activeTab === "ingest" && (
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

      {selectedSid && (activeTab === "matrix" || activeTab === "scorecard") && (
        <CellDrawer
          clientId={clientId!}
          subsectionId={selectedSid}
          focusFactId={focusFactId}
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

function monogram(name: string): string {
  return name.replace(/^@/, "").split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "—";
}
function monoColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360} 42% 42%)`;
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
    default:
      return null;
  }
}

type Sub = { id: string; label: string };
const ZONES: { id: string; label: string; tabs: Sub[] }[] = [
  // Досье + About объединены в одну зону «Компания» (обзор + структурный профиль)
  { id: "dossier", label: "Компания", tabs: [{ id: "dossier", label: "Досье" }, { id: "about", label: "Профиль" }] },
  { id: "map", label: "Map", tabs: [{ id: "matrix", label: "Matrix" }] },
  {
    id: "build", label: "Build", tabs: [
      { id: "ingest", label: "LLM report" },
      { id: "youtube", label: "YouTube" },
      { id: "audio", label: "Audio" },
      { id: "client-facts", label: "От клиента" },
      { id: "research", label: "Research" },
      { id: "work", label: "Work" },
    ],
  },
  {
    id: "health", label: "Health", tabs: [
      { id: "scorecard", label: "Scorecard" },
      { id: "punch", label: "Punch-list" },
      { id: "audit", label: "Проверка фактов" },
      { id: "interview", label: "Interview Qs" },
    ],
  },
  {
    id: "deliver", label: "Deliver", tabs: [
      { id: "brief", label: "Brief" },
      { id: "export", label: "Выгрузка" },
      { id: "artifacts", label: "Artifacts" },
      { id: "plan", label: "Plan" },
    ],
  },
];

function Tabs({ clientId, activeTab, quarter, onQuarterChange, onRunCycle, onTogglePresent }: TabsProps) {
  const nav = useNavigate();
  const activeZone = ZONES.find(z => z.tabs.some(t => t.id === activeTab)) ?? ZONES[0];
  const showSub = activeZone.tabs.length > 1 || activeZone.id === "deliver";
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  // «Пользователи» видят супер-админ и владелец данных этой компании
  const canSeeUsers = !!me.data?.is_admin
    || (me.data?.tid != null && client.data?.owner_tid === me.data.tid);

  return (
    <div className="border-b border-ink-line bg-white">
      {/* одна строка: зоны · айдентика компании (приоритет) · глобальные действия */}
      <div className="flex items-center gap-2 px-4 py-2.5">
        {ZONES.map(z => {
          const active = z.id === activeZone.id;
          return (
            <button
              key={z.id}
              onClick={() => nav(`/clients/${clientId}/${z.tabs[0].id}`)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition shrink-0
                ${active ? "bg-ink text-white font-medium" : "text-ink-mute hover:text-ink hover:bg-ink/[0.04]"}`}
            >
              <ZoneIcon id={z.id} />
              {z.label}
            </button>
          );
        })}

        {client.data?.name ? (
          <div className="ml-2 min-w-0 flex-1 flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg grid place-items-center text-[10px] font-semibold text-white select-none shrink-0"
              style={{ background: monoColor(client.data.name) }}>{monogram(client.data.name)}</span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-ink truncate leading-tight" title={client.data.name}>{client.data.name}</div>
              {client.data.sector && <div className="text-[11px] text-ink-mute truncate leading-tight">{client.data.sector}</div>}
            </div>
          </div>
        ) : <div className="flex-1" />}

        <div className="flex items-center gap-2 shrink-0">
          <SearchBox clientId={clientId} />
          <button
            onClick={() => nav(`/clients/${clientId}/methodology`)}
            className={`text-xs transition ${activeTab === "methodology" ? "text-ink font-medium" : "text-ink-mute hover:text-ink"}`}
            title="Methodology reference"
          >Methodology</button>
          <div className="flex items-center rounded-lg border border-ink-line overflow-hidden text-xs">
            <button className="px-3 py-1.5 bg-ink text-white">Analyst</button>
            <button
              onClick={() => onTogglePresent(true)}
              className="px-3 py-1.5 text-ink-mute hover:text-ink transition"
            >Present</button>
          </div>
          <UserMenu clientId={clientId} canSeeUsers={canSeeUsers} />
        </div>
      </div>

      {/* sub-tab row (hidden in present mode) */}
      {showSub && (
        <div className="flex items-center gap-1 px-4 border-t border-ink-line/60">
          {activeZone.tabs.map(t => (
            <NavLink
              key={t.id}
              to={`/clients/${clientId}/${t.id}`}
              className={`px-2.5 py-2 text-[13px] border-b-2 transition whitespace-nowrap
                ${activeTab === t.id
                  ? "border-ink text-ink font-medium"
                  : "border-transparent text-ink-mute hover:text-ink"}`}
            >
              {t.label}
            </NavLink>
          ))}

          {activeZone.id === "build" && <BuildActions clientId={clientId} />}

          {activeZone.id === "deliver" && (
            <div className="ml-auto flex items-center gap-1.5 py-1.5">
              <input
                value={quarter}
                onChange={e => onQuarterChange(e.target.value)}
                placeholder="2026Q2"
                className="w-20 text-xs border border-ink-line rounded-lg px-2 py-1 font-mono"
                title="Quarter for cycles + plan"
              />
              <span className="text-[11px] text-ink-mute pl-1">Run cycle:</span>
              <button onClick={() => onRunCycle("weekly")} className="text-xs px-2.5 py-1 rounded-lg border border-ink-line text-ink hover:bg-ink/[0.04]" title="Run weekly cycle">Weekly</button>
              <button onClick={() => onRunCycle("event")} className="text-xs px-2.5 py-1 rounded-lg border border-ink-line text-ink hover:bg-ink/[0.04]" title="Run event-driven cycle">Event</button>
              <button onClick={() => onRunCycle("quarterly")} className="text-xs px-2.5 py-1 rounded-lg border border-ink-line text-ink hover:bg-ink/[0.04]" title="Run quarterly cycle">Quarterly</button>
            </div>
          )}
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
      <button
        onClick={() => genTitles.mutate()}
        disabled={genTitles.isPending}
        title="Сгенерировать короткие заголовки (2-3 слова) для карточек без заголовка"
        className="text-xs px-2.5 py-1 rounded-lg border border-ink-line text-ink hover:bg-ink/[0.04] disabled:opacity-50 whitespace-nowrap"
      >
        {genTitles.isPending ? "Генерирую заголовки…"
          : genTitles.isSuccess ? `Готово: ${genTitles.data?.titled ?? 0} заголовков`
          : "Заголовки карточек"}
      </button>
      {totalMust > 0 && (
        <button
          onClick={() => api.downloadMustHaveFacts(clientId, clientId).catch(() => {})}
          title="Скачать must-have факты нумерованным списком для согласования с заказчиком"
          className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border border-flag-blue/40 text-flag-blue hover:bg-flag-blue/5 whitespace-nowrap"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-flag-blue" />
          Выгрузить must-have (★{totalMust})
        </button>
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
      <span>Конфиденциально · {name} Investor Relations</span>
      <span className="flex items-center gap-2.5">
        {analyst && <span>Аналитик: {analyst}</span>}
        <span className="px-2 py-0.5 rounded-md bg-ink text-white text-[10px] tracking-wide">LIVE</span>
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
          <div className="text-lg font-semibold text-ink tabular-nums">{pct}% <span className="text-ink-mute font-normal">mapped</span></div>
          <div className="text-xs text-ink-mute tabular-nums">{gaps} gaps · {quarter}</div>
        </div>
        <div className="flex items-center rounded-lg border border-ink-line overflow-hidden text-xs">
          <button onClick={onExit} className="px-3 py-1.5 text-ink-mute hover:text-ink transition">Analyst</button>
          <button className="px-3 py-1.5 bg-ink text-white">Present</button>
        </div>
      </div>
    </div>
  );
}
