// Types mirror the FastAPI response shapes.

export type Flag = "green" | "red" | "grey";
export type Channel = "online_research" | "online_interview" | "archival" | "offline_interview";
export type CycleKind = "weekly" | "event" | "quarterly";

export interface Subsection {
  id: string;
  name: string;
  sort_order: number;
}

export interface Layer {
  id: number;
  name: string;
  intimacy: number;
  primary_channels: Channel[];
  subsections: Subsection[];
}

export interface Client {
  id: string;
  name: string;
  sector?: string;
  one_liner?: string;
  founder_name?: string;
  founder_handle?: string;
  aliases?: string[];
  notes?: string;
}

export interface SeedImportResult {
  client_id: string;
  fact_count: number;
  source_count: number;
  track_count: number;
}

export interface SearchHit {
  title: string;
  url: string;
  snippet: string;
  suggested_channel: string;
}

export interface ResearchResult {
  hits: SearchHit[];
  queries_used: string[];
}

export interface FactCandidateOut {
  text: string;
  suggested_subsection_id?: string;
  suggested_subsection_name: string;
  suggested_layer_id?: number;
  suggested_layer_name: string;
  suggested_flag: Flag;
  confidence: number;
  rationale: string;
}

export interface IngestPreviewOut {
  channel: string;
  source_url: string;
  source_title: string;
  candidates: FactCandidateOut[];
}

export interface IngestConfirmOut {
  written: number[];
  skipped: number;
}

export type WorkItemStatus = "queued" | "in_progress" | "needs_review" | "done" | "blocked" | "cancelled";
export type WorkItemType = "fill_gap" | "discover" | "verify" | "deepen" | "interview" | "adjacent" | "cross_ref";

export interface WorkItem {
  id: number;
  client_id: string;
  type: WorkItemType;
  subsection_id?: string;
  source_signal: string;
  status: WorkItemStatus;
  assignee: string;
  priority: number;
  title: string;
  rationale: string;
  suggested_channel?: string;
  related_track_id?: number;
  related_fact_id?: number;
  due_date?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  notes: string;
}

export interface SynthesizeResult {
  created: number[];
  skipped: number;
}

// ── LLM Report Ingest types ──────────────────────────────────────────────────

export interface LLMResolvedCitation {
  cite_id: number;
  canonical_url: string;
  title: string;
  publisher: string;
  channel: string;
  classification_reason: string;
}

export interface LLMResolvedFact {
  text: string;
  subsection_id: string;
  flag: "green" | "red" | "grey";
  cite_ids: number[];
  confidence: number;
  raw_paraphrase: string;
  evidence_snippet: string;
  needs_review: boolean;
  snippet_source: string;
}

export interface LLMIngestPreview {
  audit_id: string;
  source_artifact_path: string;
  detected_agent: string | null;
  sources: LLMResolvedCitation[];
  facts: LLMResolvedFact[];
  notes: string[];
  stats: Record<string, number>;
}

export interface LLMIngestEdit {
  fact_idx: number;
  action: "keep" | "edit" | "drop";
  new_text?: string;
  new_subsection_id?: string;
  new_flag?: string;
}

export interface LLMIngestCommitOut {
  audit_id: string;
  committed_facts: number;
  committed_sources: number;
  skipped_facts: number;
  ingested_at: string;
}

export interface LLMIngestAuditRow {
  id: string;
  client_id: string;
  ingest_kind: string;
  source_artifact: string;
  agent: string | null;
  parsed_at: string;
  facts_emitted: number;
  facts_committed: number;
  greys_emitted: number;
  channel_warnings: number;
  expert_email: string;
  confirmed_at: string;
}

// ── YouTube Ingest ────────────────────────────────────────────────────────────

export interface YouTubeJobOut {
  job_id: string;
  status: "processing" | "done" | "error";
  error?: string | null;
  result?: YouTubePreviewResult | null;
}

export interface YouTubeVideoMeta {
  video_id: string;
  canonical_url: string;
  title: string;
  channel_name: string;
  duration_sec: number;
  upload_date: string;
  language: string | null;
}

export interface YouTubeFact {
  text: string;
  text_ru: string;
  text_en: string;
  quote: string;
  subsection_id: string;
  flag: "green" | "red" | "grey";
  confidence: number;
  evidence_snippet: string;
  source_url: string;
  snippet_start_sec: number;
  snippet_end_sec: number;
  needs_review: boolean;
  layer_warning: boolean;
}

export interface YouTubeSkipped {
  text: string;
  subsection_id: string;
  reason: string;
  source_url: string;
  evidence_snippet: string;
  override_allowed: boolean;
}

export interface YouTubePreviewResult {
  preview_id: string;
  meta: YouTubeVideoMeta;
  facts: YouTubeFact[];
  skipped: YouTubeSkipped[];
  from_cache: boolean;
  transcribe_cost_usd: number | null;
  notes: string[];
  stats: Record<string, number>;
}

export interface YouTubeCommitOut {
  committed: number;
  skipped: number;
}

export interface YouTubeHistoryRow {
  id: string;
  client_id: string;
  video_id: string | null;
  transcriber: string | null;
  transcribe_cost_usd: number | null;
  parsed_at: string;
  facts_emitted: number;
  facts_committed: number;
  channel_warnings: number;
  expert_email: string;
  confirmed_at: string | null;
}

export interface CellSummary {
  subsection_id: string;
  subsection_name: string;
  layer_id: number;
  layer_name: string;
  intimacy: number;
  n_green: number;
  n_red: number;
  n_grey: number;
  last_update?: string | null;
}

export interface Fact {
  id: number;
  text: string;
  flag: Flag;
  confidence: number;
  captured_at: string;
  evidence_snippet?: string;
  source_channel?: Channel;
  source_title?: string;
  source_url?: string;
  source_archive_url?: string;
  ingest_audit_id?: string;
}

export interface Track {
  id: number;
  plan_id: number;
  name: string;
  angle?: string;
  target_layer_ids: number[];
  target_subsection_ids: string[];
  priority: number;
}

export interface Artifact {
  id: number;
  client_id: string;
  cycle: CycleKind;
  title: string;
  body: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ArtifactSummary {
  id: number;
  client_id: string;
  cycle: CycleKind;
  title: string;
  created_at: string;
}

export interface PunchList {
  empty_cells: CellSummary[];
  cells_with_known_gaps: (CellSummary & { grey_facts: { id: number; text: string }[] })[];
  thinly_covered: CellSummary[];
}

export interface ScorecardTotals {
  green: number;
  red: number;
  grey: number;
  empty_cells: number;
}

export interface Scorecard {
  rows: CellSummary[];
  totals: ScorecardTotals;
}
