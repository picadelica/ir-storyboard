import type {
  AudioTranscript,
  Artifact, ArtifactSummary, BackupMeta, CellSummary, Client, CycleKind,
  Fact, FactCandidateOut, IngestConfirmOut, IngestPreviewOut,
  AuditResult, Entity, EntityFact, ReviewFact, DuplicatesResult, UnattributedResult, InterviewGuide,
  AboutProposal, AboutAutofillResult, FounderDiscoverResult, FounderProfilesResult,
  BriefTemplate, BriefComposeResult,
  ClientMethodologyCell, Layer, MethodologyCell, PortfolioRow, TonePreset,
  ReclassifyResult, UserOverview, SearchResult,
  LLMIngestAuditRow, LLMIngestCommitOut, LLMIngestEdit, LLMIngestPreview,
  PunchList, ResearchResult, Scorecard,
  SeedImportResult, SynthesizeResult, Track, WorkItem, MatrixExport, Dossier,
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

// Pull a human-readable message out of a failed upload response. FastAPI puts the
// message in JSON {detail: "..."}; fall back to raw text / status.
async function uploadError(r: Response): Promise<string> {
  const raw = await r.text().catch(() => "");
  try { const j = JSON.parse(raw); if (j?.detail) return String(j.detail); } catch { /* not json */ }
  return raw || `${r.status} ${r.statusText}`;
}

interface JobOut<T> {
  job_id: string;
  status: "processing" | "done" | "error";
  result: T | null;
  error: string | null;
}

// Start a background LLM job and poll its short status endpoint until done.
// Each poll is a fast request, so no single connection stays idle long enough
// for a NAT/proxy to drop it — unlike a 1–2 min synchronous call.
async function runJob<T>(startPath: string, body?: unknown, intervalMs = 2500, timeoutMs = 600_000): Promise<T> {
  const init: RequestInit = { method: "POST" };
  if (body !== undefined) init.body = JSON.stringify(body);
  const { job_id } = await call<JobOut<T>>(startPath, init);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, intervalMs));
    const job = await call<JobOut<T>>(`/jobs/${job_id}`);
    if (job.status === "done") return job.result as T;
    if (job.status === "error") throw new Error(job.error || "задача завершилась с ошибкой");
  }
  throw new Error("истекло время ожидания");
}

export const api = {
  health: () => call<{ ok: boolean }>("/health"),
  layers: () => call<Layer[]>("/layers"),
  channels: () => call<string[]>("/channels"),

  authMe: () => call<{ name: string; tid: number; auth: boolean; is_admin?: boolean }>("/auth/me"),

  // «Пользователи системы» — кто есть кто (роль + активность). Админ/владельцы.
  usersOverview: (): Promise<UserOverview[]> => call<UserOverview[]>("/users/overview"),
  authStart: () => call<{ token: string; bot_username: string; deep_link: string }>(
    "/auth/start", { method: "POST" }),
  authStatus: (token: string) => call<{ status: string; user?: { name: string; tid: number } }>(
    `/auth/status?token=${encodeURIComponent(token)}`),
  authLogout: () => call<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  listClients: (includeHidden = false) =>
    call<Client[]>("/clients" + (includeHidden ? "?include_hidden=true" : "")),
  clientsPortfolio: () => call<PortfolioRow[]>("/clients/portfolio"),
  setClientMine: (id: string, on: boolean) =>
    call<{ ok: boolean; mine: boolean }>(`/clients/${id}/mine`, {
      method: "PUT", body: JSON.stringify({ on }),
    }),
  users: () => call<{ tid: number; name: string; username: string }[]>("/users"),
  setClientOwner: (id: string, tid: number | null) =>
    call<Client>(`/clients/${id}/owner`, { method: "PUT", body: JSON.stringify({ tid }) }),
  setClientHidden: (id: string, hidden: boolean) =>
    call<Client>(`/clients/${id}/hidden`, { method: "PUT", body: JSON.stringify({ hidden }) }),

  briefTemplates: () => call<BriefTemplate[]>("/brief-templates"),
  createBriefTemplate: (b: { name: string; material_type: string; body: string }) =>
    call<BriefTemplate>("/brief-templates", { method: "POST", body: JSON.stringify(b) }),
  updateBriefTemplate: (id: number, b: Partial<{ name: string; material_type: string; body: string }>) =>
    call<BriefTemplate>(`/brief-templates/${id}`, { method: "PUT", body: JSON.stringify(b) }),
  deleteBriefTemplate: (id: number) =>
    call<{ ok: boolean }>(`/brief-templates/${id}`, { method: "DELETE" }),
  composeBrief: (clientId: string, b: { template_id: number; analyst_prompt: string; flags?: string[] | null; layer_ids?: number[] | null }) =>
    call<BriefComposeResult>(`/clients/${clientId}/brief`, { method: "POST", body: JSON.stringify(b) }),
  getClient: (id: string) => call<Client>(`/clients/${id}`),
  upsertClient: (c: Client) =>
    call<Client>("/clients", { method: "POST", body: JSON.stringify(c) }),
  patchClient: (id: string, patch: Partial<Omit<Client, "id" | "created_at" | "created_by">>) =>
    call<Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  clearClientData: (id: string) =>
    call<{
      deleted: Record<string, number>;
      backup?: BackupMeta;
      full_db_backup?: string;
    }>(`/clients/${id}/data`, { method: "DELETE" }),
  listBackups: (clientId: string) =>
    call<BackupMeta[]>(`/clients/${clientId}/backups`),
  restoreClient: (clientId: string, backupId: string) =>
    call<{ restored: Record<string, number> }>(`/clients/${clientId}/restore`, {
      method: "POST",
      body: JSON.stringify({ backup_id: backupId }),
    }),
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
  moveFact: (factId: number, toSid: string): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/move`, { method: "POST", body: JSON.stringify({ to_sid: toSid }) }),

  search: (q: string, scope: "client" | "all", clientId?: string): Promise<SearchResult> =>
    call<SearchResult>(`/search?q=${encodeURIComponent(q)}&scope=${scope}` +
      (scope === "client" && clientId ? `&client_id=${encodeURIComponent(clientId)}` : "")),

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
  researchQueries: (clientId: string) =>
    call<{ queries: string[] }>(`/clients/${clientId}/research/queries`, { method: "POST" }),
  research: (clientId: string, queries?: string[]) =>
    call<ResearchResult>(`/clients/${clientId}/research`, {
      method: "POST",
      body: JSON.stringify(queries !== undefined ? { queries } : {}),
    }),

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

  otherPdfPreview: (clientId: string, file: File): Promise<IngestPreviewOut> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_BASE}/clients/${clientId}/ingest/other-pdf/preview`, { method: "POST", body: form })
      .then(async r => { if (!r.ok) throw new Error(await uploadError(r)); return r.json(); });
  },
  otherPdfCommit: (clientId: string, sourceTitle: string,
    facts: { text: string; subsection_id: string; flag: string; rationale?: string }[]): Promise<IngestConfirmOut> =>
    call<IngestConfirmOut>(`/clients/${clientId}/ingest/other-pdf/commit`, {
      method: "POST", body: JSON.stringify({ source_title: sourceTitle, facts }),
    }),

  // Инфа от клиента — факты, присланные клиентом лично (must-have, синие)
  ingestClientFacts: (clientId: string, sourceTitle: string,
    facts: { text: string; subsection_id: string; flag?: string; rationale?: string }[]): Promise<IngestConfirmOut> =>
    call<IngestConfirmOut>(`/clients/${clientId}/ingest/client-facts`, {
      method: "POST", body: JSON.stringify({ source_title: sourceTitle, facts }),
    }),
  // Авторазбор файла от клиента (PDF, в т.ч. скан) → факты по всей матрице L1–L8
  clientFactsPreview: (clientId: string, file: File): Promise<IngestPreviewOut> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_BASE}/clients/${clientId}/ingest/client-facts/preview`, { method: "POST", body: form })
      .then(async r => { if (!r.ok) throw new Error(await uploadError(r)); return r.json(); });
  },

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

  llmReportPrompt: (clientId: string, agent: string): Promise<{ agent: string; agents: string[]; prompt: string }> =>
    call(`/clients/${clientId}/ingest/llm-report/prompt?agent=${agent}`),
  llmIngestPreviewText: (clientId: string, text: string, agentHint?: string): Promise<LLMIngestPreview> =>
    call<LLMIngestPreview>(`/clients/${clientId}/ingest/llm-report/preview-text`, {
      method: "POST", body: JSON.stringify({ text, agent_hint: agentHint }),
    }),

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
    speakerEntityId?: number | null,
  ): Promise<YouTubeCommitOut> =>
    call<YouTubeCommitOut>(`/clients/${clientId}/ingest/youtube/commit`, {
      method: "POST",
      body: JSON.stringify({
        preview_id: previewId,
        accepted_fact_ids: acceptedFactIds,
        overrides,
        expert_email: expertEmail,
        speaker_entity_id: speakerEntityId ?? null,
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

  // Переосмысление раскладки при смене методологии: превью переездов (async job) + apply
  reclassifyMethodology: (clientId: string): Promise<ReclassifyResult> =>
    runJob<ReclassifyResult>(`/clients/${clientId}/methodology/reclassify/start`),
  applyMethodologyMoves: (clientId: string, moves: { fact_id: number; to_sid: string }[]):
    Promise<{ applied: number; requested: number }> =>
    call<{ applied: number; requested: number }>(
      `/clients/${clientId}/methodology/reclassify/apply`,
      { method: "POST", body: JSON.stringify({ moves }) }),

  // fact trust / verification
  runAudit: (clientId: string): Promise<AuditResult> =>
    runJob<AuditResult>(`/clients/${clientId}/audit/start`),
  setVerification: (factId: number, body: { verification: string; note?: string; entity?: string }):
    Promise<Fact> =>
    call<Fact>(`/facts/${factId}/verification`, { method: "POST", body: JSON.stringify(body) }),
  setFactSpeaker: (factId: number, entityId: number | null): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/speaker`, { method: "POST", body: JSON.stringify({ entity_id: entityId }) }),
  // source: '' (none) | 'client' (blue, mandatory) | 'expert' (purple, important)
  setMustHave: (factId: number, source: "" | "client" | "expert"): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/must-have`, { method: "POST", body: JSON.stringify({ source }) }),
  setFactTitle: (factId: number, title: string): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/title`, { method: "POST", body: JSON.stringify({ title }) }),
  generateTitles: (clientId: string): Promise<{ available: boolean; titled: number }> =>
    runJob<{ available: boolean; titled: number }>(`/clients/${clientId}/generate-titles/start`),
  // Скачать must-have (синие) факты нумерованным списком (для согласования с заказчиком)
  downloadMustHaveFacts: async (clientId: string, clientName: string): Promise<void> => {
    const r = await fetch(`${API_BASE}/clients/${clientId}/facts/must-have/export`);
    if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => "")}`);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `must_have_${clientName || clientId}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  },
  // Досье клиента (консолидированная осведомлённость)
  dossier: (clientId: string): Promise<Dossier> =>
    call<Dossier>(`/clients/${clientId}/dossier`),
  generateDossier: (clientId: string): Promise<{ available: boolean; written: number }> =>
    runJob<{ available: boolean; written: number }>(`/clients/${clientId}/dossier/generate/start`),
  // Deliver: выгрузка содержания матрицы (JSON, тексты без ссылок)
  matrixExport: (clientId: string): Promise<MatrixExport> =>
    call<MatrixExport>(`/clients/${clientId}/matrix/export.json`),
  downloadMatrixExport: async (clientId: string, clientName: string): Promise<void> => {
    const data = await call<MatrixExport>(`/clients/${clientId}/matrix/export.json`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `matrix_${clientName || clientId}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  },
  // Deliver: markdown-описание формата JSON (чтобы заказчик мог разобрать JSON)
  matrixFormatMd: async (clientId: string): Promise<string> => {
    const r = await fetch(`${API_BASE}/clients/${clientId}/matrix/format.md`);
    if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => "")}`);
    return r.text();
  },
  downloadMatrixFormat: async (clientId: string, clientName: string): Promise<void> => {
    const r = await fetch(`${API_BASE}/clients/${clientId}/matrix/format.md`);
    if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => "")}`);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `matrix_format_${clientName || clientId}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  },
  rejectFact: (factId: number): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/reject`, { method: "POST" }),
  restoreFact: (factId: number): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/restore`, { method: "POST" }),
  reviewQueue: (clientId: string): Promise<ReviewFact[]> =>
    call<ReviewFact[]>(`/clients/${clientId}/review-queue`),
  promoteFact: (factId: number): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/promote`, { method: "POST" }),
  findDuplicates: (clientId: string): Promise<DuplicatesResult> =>
    runJob<DuplicatesResult>(`/clients/${clientId}/find-duplicates/start`),
  mergeFacts: (keepId: number, mergeIds: number[], mergedText?: string): Promise<Fact> =>
    call<Fact>(`/facts/merge`, { method: "POST", body: JSON.stringify({ keep_id: keepId, merge_ids: mergeIds, merged_text: mergedText ?? null }) }),
  // speaker attribution: scan for generic "Фаундер …" wording; rewrite to a name
  findUnattributed: (clientId: string): Promise<UnattributedResult> =>
    runJob<UnattributedResult>(`/clients/${clientId}/find-unattributed/start`),
  attributeFact: (factId: number, entityId: number | null, text: string, newFounderName?: string): Promise<Fact> =>
    call<Fact>(`/facts/${factId}/attribute`, {
      method: "POST",
      body: JSON.stringify({ entity_id: entityId, new_founder_name: newFounderName ?? null, text }),
    }),
  interviewGuide: (clientId: string): Promise<InterviewGuide> =>
    runJob<InterviewGuide>(`/clients/${clientId}/interview-guide/start`),

  // identity anchor
  entities: (clientId: string): Promise<Entity[]> =>
    call<Entity[]>(`/clients/${clientId}/entities`),
  createEntity: (clientId: string, body: Partial<Entity> & { kind: string; name: string }): Promise<Entity> =>
    call<Entity>(`/clients/${clientId}/entities`, { method: "POST", body: JSON.stringify(body) }),
  patchEntity: (entityId: number, body: Partial<Entity>): Promise<{ ok: boolean }> =>
    call(`/entities/${entityId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteEntity: (entityId: number): Promise<{ ok: boolean }> =>
    call(`/entities/${entityId}`, { method: "DELETE" }),
  addEntityFact: (entityId: number, body: Partial<EntityFact>): Promise<EntityFact> =>
    call<EntityFact>(`/entities/${entityId}/facts`, { method: "POST", body: JSON.stringify(body) }),
  deleteEntityFact: (factId: number): Promise<{ ok: boolean }> =>
    call(`/entity-facts/${factId}`, { method: "DELETE" }),

  // company About auto-fill (background job → proposals → commit accepted)
  autofillCompany: (clientId: string, opts?: { pasted?: string; pasted_url?: string; pasted_title?: string; use_web?: boolean }): Promise<AboutAutofillResult> =>
    runJob<AboutAutofillResult>(`/clients/${clientId}/company/autofill/start`, opts ?? {}),
  commitCompanyFacts: (clientId: string, proposals: AboutProposal[]): Promise<{ committed: number }> =>
    call(`/clients/${clientId}/company/autofill/commit`, { method: "POST", body: JSON.stringify({ proposals }) }),
  // авто-поиск фаундеров + их профилей (background job → проверка аналитиком)
  discoverFounders: (clientId: string): Promise<FounderDiscoverResult> =>
    runJob<FounderDiscoverResult>(`/clients/${clientId}/founders/discover/start`),
  // поиск профилей + фото по конкретному фаундеру
  findFounderProfiles: (clientId: string, name: string): Promise<FounderProfilesResult> =>
    runJob<FounderProfilesResult>(`/clients/${clientId}/founders/profiles/start`, { name }),
};
