import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "./api";
import type { Layer } from "./types";
import Sidebar from "./components/Sidebar";
import MatrixGrid from "./components/MatrixGrid";
import CellDrawer from "./components/CellDrawer";
import CycleRunner from "./components/CycleRunner";
import ArtifactsView from "./components/ArtifactsView";
import PunchListView from "./components/PunchListView";
import InterviewView from "./components/InterviewView";
import ScorecardView from "./components/ScorecardView";
import WorkView from "./components/WorkView";
import ResearchView from "./components/ResearchView";
import IngestLLMReport from "./components/IngestLLMReport";
import IngestYouTube from "./components/IngestYouTube";

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
  const clients = useQuery({ queryKey: ["clients"], queryFn: api.listClients });
  if (clients.isLoading) return <div className="p-8 text-sm text-ink-mute">Loading…</div>;
  if (clients.data && clients.data.length > 0)
    return <Navigate to={`/clients/${clients.data[0].id}/matrix`} replace />;
  return <EmptyState />;
}

function EmptyState() {
  return (
    <div className="h-screen flex">
      <Sidebar quarter="2026Q2" onQuarterChange={() => {}} onRunCycle={() => {}} />
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
  const activeTab = tab ?? "matrix";

  const [quarter, setQuarter] = useState("2026Q2");
  const [selectedSid, setSelectedSid] = useState<string | undefined>();
  const [cycleKind, setCycleKind] = useState<"weekly" | "event" | "quarterly" | null>(null);
  const [pickedArtifactId, setPickedArtifactId] = useState<number | undefined>();

  const layers = useQuery<Layer[]>({ queryKey: ["layers"], queryFn: api.layers });

  const onJumpToCell = (sid: string) => {
    nav(`/clients/${clientId}/matrix`);
    setSelectedSid(sid);
  };

  return (
    <div className="h-screen flex">
      <Sidebar
        clientId={clientId}
        quarter={quarter}
        onQuarterChange={setQuarter}
        onRunCycle={(k) => setCycleKind(k)}
      />

      <main className="flex-1 flex flex-col overflow-hidden">
        <Tabs clientId={clientId!} activeTab={activeTab} />

        <div className="flex-1 overflow-y-auto">
          {activeTab === "matrix" && (
            <MatrixGrid
              clientId={clientId!}
              selectedSubsectionId={selectedSid}
              onSelectCell={setSelectedSid}
            />
          )}
          {activeTab === "punch" && (
            <PunchListView clientId={clientId!} onJumpToCell={onJumpToCell} />
          )}
          {activeTab === "interview" && <InterviewView clientId={clientId!} />}
          {activeTab === "scorecard" && <ScorecardView clientId={clientId!} />}
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
        </div>
      </main>

      {selectedSid && activeTab === "matrix" && (
        <CellDrawer
          clientId={clientId!}
          subsectionId={selectedSid}
          onClose={() => setSelectedSid(undefined)}
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

function Tabs({ clientId, activeTab }: { clientId: string; activeTab: string }) {
  const tabs = [
    { id: "matrix",    label: "Matrix" },
    { id: "ingest",    label: "Ingest" },
    { id: "youtube",   label: "YouTube" },
    { id: "research",  label: "Research" },
    { id: "work",      label: "Work" },
    { id: "punch",     label: "Punch-list" },
    { id: "interview", label: "Interview Qs" },
    { id: "scorecard", label: "Scorecard" },
    { id: "artifacts", label: "Artifacts" },
  ];
  return (
    <div className="flex items-center gap-0 border-b border-ink-line bg-white px-4">
      {tabs.map(t => (
        <NavLink
          key={t.id}
          to={`/clients/${clientId}/${t.id}`}
          className={`px-4 py-3 text-sm border-b-2 transition
            ${activeTab === t.id
              ? "border-ink text-ink font-medium"
              : "border-transparent text-ink-mute hover:text-ink"}`}
        >
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}
