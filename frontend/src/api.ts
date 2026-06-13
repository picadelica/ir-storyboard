import type {
  AudioTranscript,
  Artifact, ArtifactSummary, CellSummary, Client, CycleKind,
  Fact, FactCandidateOut, IngestConfirmOut, IngestPreviewOut,
  ClientMethodologyCell, Layer, MethodologyCell, TonePreset,
  LLMIngestAuditRow, LLMIngestCommitOut, LLMIngestEdit, LLMIngestPreview,
  PunchList, ResearchResult, Scorecard,
  SeedImportResult, SynthesizeResult, Track, WorkItem,
  YouTubeCommitOut, YouTubeHistoryRow, YouTubeJobOut, YouTubePreviewResult,
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
  patchClient: (id: string, patch: Partial<Omit<Client, "id" | "created_at" | "created_by">>) =>
    call<Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
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
    rationale?: string;
  }) => call<Fact>(`/clients/${clientId}/cells/${sid}/facts`, {
    method: "POST", body: JSON.stringify(body),
  }),
  patchFact: (factId: number, body: { text?: string; flag?: string; confidence?: number; rationale?: string }) =>
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
  research: (clientId: string) =>
    call<ResearchResult>(`/clients/${clientId}/research`, { method: "POST" }),

  ingestPreview: (clientId: string, body: {
    channel: string; source_url: string; source_title: string; text: string;
  }) => call<IngestPreviewOut>(`/clients/${clientId}/ingest/preview`, {
    method: "POST", body: JSON.stringify(body),
  }),

  ingestConfirm: (clientId: string, facts: {
    text: string; subsection_id: string; flag: string; channel: string;
    source_url?: string; source_title?: string; evidence_snippet?: string; confidence?: number;
    rationale?: string;
  }[]) => call<IngestConfirmOut>(`/clients/${clientId}/ingest/confirm`, {
    method: "POST", body: JSON.stringify({ facts }),
  }),

  synthesizeWorkItems: (clientId: string, quarter?: string) => {
    const q = quarter ? `?quarter=${quarter}` : "";
    return call<SynthesizeResult>(`/clients/${clientId}/work-items/synthesize${q}`, { method: "POST" });
  },

  // LLM Report Ingest
  llmIngestPreview: (clientId: string, file: File, agentHint?: string): Promise<LLMIngestPreview> => {
    const form = new FormData();
    form.append("file", file);
    if (agentHint) form.append("agent_hint", agentHint);
    return fetch(`${API_BASE}/clients/${clientId}/ingest/llm-report/preview`, {
      method: "POST",
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`${res.status} ${res.statusText} — ${detail}`);
      }
      return res.json() as Promise<LLMIngestPreview>;
    });
  },

  llmIngestCommit: (
    clientId: string,
    preview: LLMIngestPreview,
    edits: LLMIngestEdit[],
    expertEmail: string,
  ): Promise<LLMIngestCommitOut> =>
    call<LLMIngestCommitOut>(`/clients/${clientId}/ingest/llm-report/commit`, {
      method: "POST",
      body: JSON.stringify({ preview, edits, expert_email: expertEmail }),
    }),

  llmIngestHistory: (clientId: string): Promise<LLMIngestAuditRow[]> =>
    call<LLMIngestAuditRow[]>(`/clients/${clientId}/ingest/llm-report/history`),

  // ── YouTube Ingest ──────────────────────────────────────────────────────────
  youtubePreviewStart: (clientId: string, url: string): Promise<YouTubeJobOut> =>
    call<YouTubeJobOut>(`/clients/${clientId}/ingest/youtube/preview`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  youtubePreviewStatus: (clientId: string, jobId: string): Promise<YouTubeJobOut> =>
    call<YouTubeJobOut>(`/clients/${clientId}/ingest/youtube/preview/${jobId}`),

  youtubeCommit: (
    clientId: string,
    previewId: string,
    acceptedFactIds: number[],
    overrides: Array<{ fact_idx: number; force_keep: boolean }>,
    expertEmail: string,
  ): Promise<YouTubeCommitOut> =>
    call<YouTubeCommitOut>(`/clients/${clientId}/ingest/youtube/commit`, {
      method: "POST",
      body: JSON.stringify({
        preview_id: previewId,
        accepted_fact_ids: acceptedFactIds,
        overrides,
        expert_email: expertEmail,
      }),
    }),

  youtubeHistory: (clientId: string): Promise<YouTubeHistoryRow[]> =>
    call<YouTubeHistoryRow[]>(`/clients/${clientId}/ingest/youtube/history`),

  youtubePreviewById: (clientId: string, previewId: string): Promise<YouTubePreviewResult> =>
    call<YouTubePreviewResult>(`/clients/${clientId}/ingest/youtube/preview-by-id/${previewId}`),

  // ── Audio file Ingest (same job/preview/commit contract as YouTube) ─────────
  audioPreviewStart: (clientId: string, file: File, title?: string): Promise<YouTubeJobOut> => {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    return fetch(`${API_BASE}/clients/${clientId}/ingest/audio/preview`, {
      method: "POST",
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`${res.status} ${res.statusText} — ${detail}`);
      }
      return res.json() as Promise<YouTubeJobOut>;
    });
  },

  audioPreviewStatus: (clientId: string, jobId: string): Promise<YouTubeJobOut> =>
    call<YouTubeJobOut>(`/clients/${clientId}/ingest/audio/preview/${jobId}`),

  /** Absolute URL of the original uploaded audio file, for <audio src>. */
  audioSourceUrl: (clientId: string, sha: string): string =>
    `${API_BASE}/clients/${clientId}/ingest/audio/source/${sha}`,

  /** Fetch the cached transcript (segments) for an uploaded audio file. */
  audioTranscript: (clientId: string, sha: string): Promise<AudioTranscript> =>
    call<AudioTranscript>(`/clients/${clientId}/ingest/audio/transcript/${sha}`),

  audioCommit: (
    clientId: string,
    previewId: string,
    acceptedFactIds: number[],
    overrides: Array<Record<string, unknown>>,
    expertEmail: string,
  ): Promise<YouTubeCommitOut> =>
    call<YouTubeCommitOut>(`/clients/${clientId}/ingest/audio/commit`, {
      method: "POST",
      body: JSON.stringify({
        preview_id: previewId,
        accepted_fact_ids: acceptedFactIds,
        overrides,
        expert_email: expertEmail,
      }),
    }),

  // ── Methodology ─────────────────────────────────────────────────────────────
  methodology: (): Promise<MethodologyCell[]> => call<MethodologyCell[]>("/methodology"),

  updateMethodology: (subsectionId: string, description: string): Promise<MethodologyCell> =>
    call<MethodologyCell>(`/methodology/${subsectionId}`, {
      method: "PATCH",
      body: JSON.stringify({ description }),
    }),

  tonePresets: (): Promise<TonePreset[]> => call<TonePreset[]>("/tone-presets"),

  clientMethodology: (clientId: string): Promise<ClientMethodologyCell[]> =>
    call<ClientMethodologyCell[]>(`/clients/${clientId}/methodology`),

  updateClientMethodology: (clientId: string, subsectionId: string, note: string):
    Promise<ClientMethodologyCell> =>
    call<ClientMethodologyCell>(`/clients/${clientId}/methodology/${subsectionId}`, {
      method: "PATCH",
      body: JSON.stringify({ note }),
    }),
};
