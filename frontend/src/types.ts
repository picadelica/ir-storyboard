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
  tone_preset?: string;
  created_at?: string;
  created_by?: string | null;
  owner_tid?: number | null;    // владелец данных компании
  hidden?: boolean;
}

export interface MethodologyCell {
  subsection_id: string;
  subsection_name: string;
  layer_id: number;
  layer_name: string;
  sort_order: number;
  description: string;
}

export interface ClientMethodologyCell extends MethodologyCell {
  client_note: string;
}

export interface MethodologyMove {
  fact_id: number;
  title: string;
  text: string;
  from_sid: string;
  to_sid: string;
  confidence: number;
  rationale: string;
}

export interface ReclassifyResult {
  moves: MethodologyMove[];
  moved: number;
  total: number;
}

export interface UserOverview {
  tid: number;
  name: string;
  username: string;
  first_seen: string | null;
  last_seen: string | null;
  owned_clients: string[];
  facts_created: number;
  facts_approved: number;
  actions: number;          // всего действий над карточками (переносы/склейки/правки/…)
  is_admin: boolean;
}

// админка: запись глобального журнала действий над карточками
export interface AdminActivityEntry {
  id: number;
  fact_id: number;
  client_id: string | null;
  client_name: string;
  action: string;           // created|moved|edited|merged|speaker_renamed|…
  from_sid: string | null;
  to_sid: string | null;
  detail: string;
  actor_tid: number | null;
  actor_name: string;
  methodology_version: number | null;
  at: string;
  fact_title: string;
  fact_text: string;        // выдержка (карточка могла быть удалена — тогда пусто)
}

export interface TonePreset {
  id: string;
  label: string;
  description: string;
  sample: string;
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
  assignee_tid?: number | null;
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
  rationale?: string;
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
  new_rationale?: string;
}

export interface LLMIngestCommitOut {
  audit_id: string;
  committed_facts: number;
  committed_sources: number;
  skipped_facts: number;
  ingested_at: string;
  held_facts?: number;
}

export interface ReviewFact {
  id: number;
  subsection_id: string;
  text: string;
  flag: string;
  verification: string;
  verification_note: string;
  entity: string;
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

// ── Client data backups ──────────────────────────────────────────────────────

export interface BackupMeta {
  id: string;
  created_at: string | null;
  path: string;
  counts: Record<string, number>;
  size_bytes: number;
}

// ── YouTube Ingest ────────────────────────────────────────────────────────────

export interface YouTubeJobOut {
  job_id: string;
  status: "processing" | "done" | "error";
  stage?: string | null;   // человекочитаемый этап (прогресс в UI)
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
  view_count?: number | null;
  like_count?: number | null;
  description?: string;
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
  rationale?: string;
}

export interface YouTubeSkipped {
  text: string;
  text_ru: string;
  text_en: string;
  quote: string;
  subsection_id: string;
  flag: string;
  confidence: number;
  reason: string;
  source_url: string;
  evidence_snippet: string;
  snippet_start_sec: number;
  snippet_end_sec: number;
  override_allowed: boolean;
  rationale?: string;
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
  confirmed_at?: string | null;
  video_brief?: string;
  cell_briefs?: Record<string, string>;
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

export interface TranscriptSegment {
  text: string;
  start: number;
  end: number;
}

export interface AudioTranscript {
  title: string;
  duration_sec: number;
  segments: TranscriptSegment[];
}

export interface BriefTemplate {
  id: number;
  name: string;
  material_type: string;
  body: string;
  created_by?: string | null;
  updated_at?: string | null;
}

export interface BriefComposeResult {
  md: string;
  json_bundle: unknown;
  fact_count: number;
}

export interface PortfolioRow {
  id: string;
  name: string;
  sector?: string | null;
  covered: number;
  total: number;
  mine?: boolean;
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
  n_must?: number;
  n_must_client?: number;   // синяя звезда (клиент / без пометки)
  n_must_expert?: number;   // фиолетовая звезда (эксперт)
  last_update?: string | null;
  channels?: Channel[];
}

export interface SearchHit {
  fact_id: number;
  client_id: string;
  client_name: string;
  subsection_id: string;
  subsection_name: string;
  title: string;
  text: string;
  flag: Flag;
  state: string;
}

export interface SearchResult {
  query: string;
  scope: "client" | "all";
  results: SearchHit[];
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
  rationale?: string;
  created_by?: string | null;
  snippet_start_sec?: number | null;
  ingest_kind?: string | null;
  audio_sha?: string | null;
  verification?: string;        // unverified | verified | suspect | refuted
  verification_note?: string;
  entity?: string;              // attributed subject on conflation
  state?: string;               // active | review | rejected
  speaker_entity_id?: number | null;  // which founder this fact is from
  speaker_name?: string | null;
  about_company?: string;       // факт про другую компанию (характеризует спикера)
  title?: string;               // short 2-3 word card title
  must_have?: boolean;          // client-provided must-have → blue
  must_have_by?: string;        // '' | 'client' (blue) | 'expert' (purple)
  merged_into?: number | null;  // set → hidden, folded into fact #merged_into
  n_sources?: number;           // corroboration count
  created_by_tid?: number | null;
  approved_by?: string;         // кто одобрил черновик (владелец)
  approved_at?: string | null;
  merged_by?: string;           // автор слияния
}

export interface DupFact {
  id: number;
  text: string;
  flag: string;
  source_url: string;
  source_title: string;
  source_channel: string;
  source_publisher: string;
  source_archive_url: string;
  snippet_start_sec: number | null;
  ingest_audit_id: string;
  ingest_kind: string;
  captured_at: string;
}

export interface DuplicateGroup {
  subsection_id: string;
  keep: number;
  ids: number[];
  reason: string;
  merged_text: string;
  facts: DupFact[];
}

export interface DuplicatesResult {
  available: boolean;
  groups: DuplicateGroup[];
}

export interface AttribItem {
  id: number;
  subsection_id: string;
  layer_id: number;
  text: string;
  generic: string;
  rewrite_template: string;
  proposed_text: string;
  needs_choice: boolean;
  must_be_concrete: boolean;
}

export interface UnattributedResult {
  available: boolean;
  founders: { id: number | null; name: string }[];   // id=null → derived from company card
  items: AttribItem[];
}

export interface GuideGround {
  id: number;
  text: string;
}

export interface GuideQuestion {
  question: string;
  grounds: GuideGround[];
  targets: string[];
  know: string;
  close: string;
  followups: string[];
}

export interface GuideArc {
  title: string;
  questions: GuideQuestion[];
}

export interface InterviewGuide {
  available: boolean;
  dossier: string;
  diagnosis: { covered: string; gaps: string; priorities: string[] };
  arcs: GuideArc[];
  n_facts: number;
}

export interface EntityFact {
  id: number;
  key: string;
  value: string;
  source_url: string;
  source_title: string;
  as_of?: string | null;
  verified: boolean;
  sort_order: number;
  section?: string;   // profile | sites | funding | history | product | metrics | ""
}

export interface AboutProposal {
  section: string;
  key: string;
  value: string;
  source_url: string;
  source_title: string;
  as_of?: string | null;
  origin: string;   // matrix | web
}

export interface AboutAutofillResult {
  available: boolean;
  proposals: AboutProposal[];
  stats: { from_matrix: number; from_web: number; dropped_ungrounded: number; duplicates: number };
}

export interface FounderProposal {
  name: string;
  role: string;
  source_url: string;
  links: Record<string, string>;   // label → url (LinkedIn / X / Wikipedia / Сайт)
  origin: string;                  // web
}

export interface FounderDiscoverResult {
  available: boolean;
  founders: FounderProposal[];
  stats: { from_web: number; dropped_ungrounded: number; duplicates: number };
}

export interface FounderProfilesResult {
  available: boolean;
  links: Record<string, string>;   // label → url (LinkedIn / X / Сайт / GitHub …)
  photo: string;                   // url аватара или ""
  stats: { from_web: number; dropped_ungrounded: number };
}

export interface Entity {
  id: number;
  kind: string;                 // company | founder | decoy
  name: string;
  role: string;
  canonical_url: string;
  links: Record<string, string>;
  note: string;
  confirmed: boolean;
  sort_order: number;
  facts: EntityFact[];
}

// внешняя компания, упомянутая под клиентом (GetTaxi, прошлые компании фаундера, конкурент)
export interface MentionedCompany {
  id: number;
  client_id: string;
  name: string;
  logo: string;
  note: string;
  sort_order: number;
  is_current?: boolean;   // сама текущая компания клиента (авто-запись; тег = «держать факт в L3-8»)
}

// тот же фаундер (по имени) в другой компании — для предложения влить профиль
export interface FounderMatch {
  id: number;
  client_id: string;
  client_name: string;
  name: string;
  role: string;
  canonical_url: string;
  links: Record<string, string>;
  note: string;
}

export interface AuditFact {
  id: number;
  verdict: string;              // suspect | refuted
  entity: string;
  reason: string;
  subsection_id: string;
  text: string;
}

export interface AuditResult {
  available: boolean;
  canonical: { company?: string; founders?: string[]; decoys?: string[] };
  summary: string;
  facts: AuditFact[];
  n_facts: number;
  applied: number;
}

// ── Deliver: matrix export (тексты без ссылок) ────────────────────────────────

export interface ExportCard {
  matrix_no: string;          // номер ячейки в матрице (напр. "1.1")
  subsection_name: string;
  layer_id: number;           // слой 1–8
  sublayer: number;           // подсекция внутри слоя 1–3 (вторая цифра matrix_no числом)
  layer_name: string;
  fact_id: number;
  title: string;
  text: string;
  card_color: Flag;           // цвет карточки (флаг)
  star: "blue" | "purple" | null;  // цвет звезды (must-have)
}

export interface MatrixExport {
  export: {
    client_id: string;
    client_name: string;
    sector: string;
    one_liner: string;
    card_count: number;
    description: string;
    generated_at?: string;
    legend: {
      card_color: Record<string, string>;
      star_color: Record<string, string>;
    };
  };
  company_card: {
    name: string;
    role: string;
    note: string;
    facts: { section: string; key: string; value: string }[];
  } | null;
  cards: ExportCard[];
  readme: string;   // markdown-описание формата (самодокументируемость JSON)
}

// ── Client dossier (консолидированное досье осведомлённости) ──────────────────

export interface DossierLayer {
  layer_id: number;
  name: string;
  intimacy: number;
  summary: string;
  n_green: number;
  n_red: number;
  n_grey: number;
  facts: number;
  cells_total: number;
  cells_filled: number;
  channels: Channel[];
  last_update?: string | null;
  n_must_client: number;
  n_must_expert: number;
  corroborated: number;
  facts_total: number;
  cells: DossierCell[];
}

export interface DossierCell {
  subsection_id: string;
  subsection_name: string;
  n_green: number;
  n_red: number;
  n_grey: number;
  facts: number;
  must_have: boolean;
  corroborated: boolean;
  last_update?: string | null;
}

export interface Dossier {
  client: { id: string; name: string; sector?: string; one_liner?: string };
  exec_summary: string;
  generated_at?: string | null;
  tone: string;
  overall: {
    facts: number;
    coverage_pct: number;
    red: number;
    must_client: number;
    must_expert: number;
    corroborated_pct: number;
    last_update?: string | null;
  };
  layers: DossierLayer[];
  staleness: { generated_at?: string | null; new_facts: number };
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

// ── Мониторинг ───────────────────────────────────────────────────────────────

export type WatchlistKind = "youtube_channel" | "rss" | "search_query";

export interface WatchlistItem {
  id: number;
  client_id: string;
  kind: WatchlistKind;
  config: { url?: string; feed_url?: string; query?: string; window?: string };
  label: string;
  speaker_entity_id: number | null;
  speaker_name?: string | null;
  schedule: string;
  status: "active" | "paused";
  last_checked_at: string | null;
  last_error: string;
  new_count?: number;
  created_at: string;
}

export interface MonitorCandidate {
  id: number;
  client_id: string;
  watchlist_item_id: number;
  url: string;
  norm_url: string;
  title: string;
  published_at: string;
  duration_sec: number | null;
  thumb_url: string;
  relevance: "likely" | "unclear" | "unlikely";
  relevance_note: string;
  state: "new" | "ingesting" | "ingested" | "dismissed";
  source_id: number | null;
  item_label?: string;
  item_kind?: WatchlistKind;
  speaker_entity_id?: number | null;
  created_at: string;
}

export interface WatchlistSuggestion {
  channel_name: string;
  count: number;
  sample_url: string;
}

export interface CheckResult {
  client_id?: string;
  items_checked?: number;
  found: number;
  new: number;
  errors?: { label: string; error: string }[];
}

export interface DigestBlock {
  theme: string;
  start_sec: number;
  end_sec: number;
  gist: string;
}

export interface DigestMoment {
  quote: string;
  timecode_sec: number;
  note: string;
  unverified?: boolean;
}

export interface DigestComparisonDetail {
  topic: string;
  kind: "shifted" | "reversed" | "new" | "gone_quiet" | "rhetoric_drift";
  was: { quote: string; date: string };
  now: { quote: string; timecode_sec: number; unverified?: boolean };
  note: string;
}

export interface DigestPayload {
  main_motif: string;
  blocks: DigestBlock[];
  key_moments: DigestMoment[];
  indirect: string[];
  comparison: { text: string; details: DigestComparisonDetail[] } | null;
}

export interface EpisodeDigest {
  id: number;
  client_id: string;
  norm_url: string;
  source_id: number | null;
  speaker_entity_id: number;
  episode_date: string;
  title: string;
  payload: DigestPayload;
  model: string;
  created_at: string;
}

export interface DigestJobResult {
  status: "ok" | "no_speaker" | "no_transcript";
  digest?: EpisodeDigest;
  reason?: string;
  cached?: boolean;
}

export interface DuplicateHint {
  idx: number;
  score: number;
  fact: { id: number; text: string; flag: string; title: string; subsection_id: string };
}
