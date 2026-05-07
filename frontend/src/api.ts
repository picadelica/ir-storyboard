import type {
  Artifact, ArtifactSummary, CellSummary, Client, CycleKind,
  Fact, Layer, PunchList, Scorecard, SeedImportResult, SynthesizeResult, Track, WorkItem,
} from "./types";

const API_BASE = "/api";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = "";
    try { detail = await res.text(); } catch { /* ignore */ }
    throw new Error(`${res.status} ${res.statusText} — ${detail}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => call<{ ok: boolean }>("/health"),
  layers: () => call<Layer[]>("/layers"),
  channels: () => call<string[]>("/channels"),

  listClients: () => call<Client[]>("/clients"),
  getClient: (id: string) => call<Client>(`/clients/${id}`),
  upsertClient: (c: Client) =>
    call<Client>("/clients", { method: "POST", body: JSON.stringify(c) }),
  seedAccumulator: () =>
    call<{ ok: boolean; client_id: string }>("/clients/accumulator/seed-accumulator", {
      method: "POST", body: "{}",
    }),
  importSeedYaml: (clientId: string, yamlContent: string, force = false) =>
    call<SeedImportResult>(
      `/clients/${clientId}/import-seed-yaml${force ? "?force=true" : ""}`,
      { method: "POST", body: JSON.stringify({ yaml_content: yamlContent }) },
    ),

  matrixView: (clientId: string) => call<CellSummary[]>(`/clients/${clientId}/matrix`),

  cellFacts: (clientId: string, sid: string) =>
    call<Fact[]>(`/clients/${clientId}/cells/${sid}/facts`),
  addFact: (clientId: string, sid: string, body: {
    text: string; flag: string; channel: string;
    source_title?: string; source_url?: string;
    evidence_snippet?: string; confidence?: number;
  }) => call<Fact>(`/clients/${clientId}/cells/${sid}/facts`, {
    method: "POST", body: JSON.stringify(body),
  }),
  patchFact: (factId: number, body: { text?: string; flag?: string; confidence?: number }) =>
    call<Fact>(`/facts/${factId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteFact: (factId: number) =>
    call<{ ok: boolean }>(`/facts/${factId}`, { method: "DELETE" }),

  tracks: (clientId: string, quarter: string) =>
    call<Track[]>(`/clients/${clientId}/plans/${quarter}/tracks`),
  addTrack: (clientId: string, quarter: string, body: {
    name: string; angle?: string; target_layer_ids: number[];
    target_subsection_ids: string[]; priority?: number;
  }) => call<Track>(`/clients/${clientId}/plans/${quarter}/tracks`, {
    method: "POST", body: JSON.stringify(body),
  }),

  runWeekly: (clientId: string, body: { quarter: string; week_label?: string; max_facts?: number }) =>
    call<Artifact>(`/clients/${clientId}/cycles/weekly`, {
      method: "POST", body: JSON.stringify(body),
    }),
  runEvent: (clientId: string, body: { event_text: string; landed_subsection_id: string; quarter?: string }) =>
    call<Artifact>(`/clients/${clientId}/cycles/event`, {
      method: "POST", body: JSON.stringify(body),
    }),
  runQuarterly: (clientId: string, body: { quarter: string; traversal?: string; facts_per_subsection?: number }) =>
    call<Artifact>(`/clients/${clientId}/cycles/quarterly`, {
      method: "POST", body: JSON.stringify(body),
    }),

  listArtifacts: (clientId: string, cycle?: CycleKind) => {
    const q = cycle ? `?cycle=${cycle}` : "";
    return call<ArtifactSummary[]>(`/clients/${clientId}/artifacts${q}`);
  },
  getArtifact: (artifactId: number) => call<Artifact>(`/artifacts/${artifactId}`),

  punchList: (clientId: string) => call<PunchList>(`/clients/${clientId}/punch-list`),
  interviewQuestions: (clientId: string) =>
    call<{ markdown: string }>(`/clients/${clientId}/interview-questions`),
  scorecard: (clientId: string) => call<Scorecard>(`/clients/${clientId}/scorecard`),

  notebooklmBundleUrl: (clientId: string, ids: number[]) =>
    `${API_BASE}/clients/${clientId}/notebooklm-bundle?artifact_ids=${ids.join(",")}`,

  listWorkItems: (clientId: string, params?: { status?: string[]; type?: string[] }) => {
    const q = new URLSearchParams();
    params?.status?.forEach(s => q.append("status", s));
    params?.type?.forEach(t => q.append("type", t));
    const qs = q.toString() ? `?${q}` : "";
    return call<WorkItem[]>(`/clients/${clientId}/work-items${qs}`);
  },
  getWorkItem: (wid: number) => call<WorkItem>(`/work-items/${wid}`),
  createWorkItem: (clientId: string, body: Partial<WorkItem>) =>
    call<WorkItem>(`/clients/${clientId}/work-items`, {
      method: "POST", body: JSON.stringify(body),
    }),
  patchWorkItem: (wid: number, body: Partial<WorkItem>) =>
    call<WorkItem>(`/work-items/${wid}`, { method: "PATCH", body: JSON.stringify(body) }),
  synthesizeWorkItems: (clientId: string, quarter?: string) => {
    const q = quarter ? `?quarter=${quarter}` : "";
    return call<SynthesizeResult>(`/clients/${clientId}/work-items/synthesize${q}`, { method: "POST" });
  },
};
