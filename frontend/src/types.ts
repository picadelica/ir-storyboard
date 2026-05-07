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
  source_channel?: Channel;
  source_title?: string;
  source_url?: string;
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
