-- IR Storyboard matrix schema
-- 8 concentric narrative layers x N subsections x facts (tagged green/red/grey)
-- 4 ingestion channels mapped to layer affinity
-- Plans + narrative tracks per quarter
-- Cycle artifacts (weekly / event / quarterly)

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------
-- Reference data: layers and subsections (8 concentric layers)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS layers (
    id              INTEGER PRIMARY KEY,           -- 1..8
    code            TEXT NOT NULL UNIQUE,          -- e.g. 'FOUNDER_PERSONAL'
    name            TEXT NOT NULL,                 -- human-readable
    intimacy        INTEGER NOT NULL,              -- 1 = innermost (founder personal), 8 = outermost (PEST)
    primary_channels TEXT NOT NULL                 -- JSON array of channel codes
);

CREATE TABLE IF NOT EXISTS subsections (
    id              TEXT PRIMARY KEY,              -- e.g. '1.1' for Origin & Childhood
    layer_id        INTEGER NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,                 -- e.g. 'ORIGIN_CHILDHOOD'
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    UNIQUE(layer_id, code)
);

-- ----------------------------------------------------------------
-- Clients (companies / personalities the agency supports)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clients (
    id              TEXT PRIMARY KEY,              -- slug, e.g. 'accumulator'
    name            TEXT NOT NULL,
    sector          TEXT,                          -- deeptech sub-sector
    one_liner       TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------
-- Cells: client x subsection (one row per (client, subsection) pair)
-- A cell is the bucket facts live in.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cells (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    subsection_id   TEXT NOT NULL REFERENCES subsections(id) ON DELETE CASCADE,
    UNIQUE(client_id, subsection_id)
);

-- ----------------------------------------------------------------
-- Sources: each ingested item leaves a source record
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel         TEXT NOT NULL CHECK(channel IN (
                       'online_research',
                       'online_interview',
                       'archival',
                       'offline_interview')),
    title           TEXT,
    url             TEXT,
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT
);

-- ----------------------------------------------------------------
-- Facts: the actual atoms. Each fact lives in exactly one cell.
-- flag: green = positive signal, red = negative signal,
--       grey = explicit "no info / unknown / cannot fill via this channel"
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id         INTEGER NOT NULL REFERENCES cells(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    flag            TEXT NOT NULL CHECK(flag IN ('green','red','grey')),
    source_id       INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    confidence      REAL DEFAULT 1.0,              -- 0..1, optional
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_until     DATE                           -- NULL = persistent; else freshness window
);

CREATE INDEX IF NOT EXISTS idx_facts_cell ON facts(cell_id);
CREATE INDEX IF NOT EXISTS idx_facts_flag ON facts(flag);

-- ----------------------------------------------------------------
-- Plans: per client, per quarter
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    quarter         TEXT NOT NULL,                 -- e.g. '2026Q2'
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, quarter)
);

-- A narrative track is one positioning thread inside a plan.
-- target_layer_ids: where this track lives in the matrix.
-- target_subsection_ids: which green flags it tries to advance.
CREATE TABLE IF NOT EXISTS narrative_tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    angle           TEXT,                          -- the "так звучит история" angle
    target_layer_ids        TEXT,                  -- JSON array of int
    target_subsection_ids   TEXT,                  -- JSON array of subsection ids
    priority        INTEGER DEFAULT 1
);

-- ----------------------------------------------------------------
-- Cycle artifacts: every weekly / event / quarterly run produces one.
-- body is markdown; meta is JSON.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    cycle           TEXT NOT NULL CHECK(cycle IN ('weekly','event','quarterly')),
    title           TEXT,
    body            TEXT,
    meta            TEXT,                          -- JSON: layer_focus, fact_ids, track_id, ...
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_client_cycle ON artifacts(client_id, cycle);

-- ----------------------------------------------------------------
-- Work items: process layer on top of the punch-list
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK(type IN (
                       'fill_gap', 'discover', 'verify', 'deepen',
                       'interview', 'adjacent', 'cross_ref'
                   )),
    subsection_id   TEXT REFERENCES subsections(id),
    source_signal   TEXT NOT NULL CHECK(source_signal IN (
                       'empty_cells', 'known_gaps', 'thin_coverage',
                       'low_confidence', 'manual', 'track_alignment',
                       'contradiction'
                   )),
    status          TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
                       'queued', 'in_progress', 'needs_review',
                       'done', 'blocked', 'cancelled'
                   )),
    assignee        TEXT DEFAULT '',
    priority        INTEGER DEFAULT 3,
    title           TEXT NOT NULL,
    rationale       TEXT DEFAULT '',
    suggested_channel TEXT,
    related_track_id INTEGER REFERENCES narrative_tracks(id) ON DELETE SET NULL,
    related_fact_id INTEGER REFERENCES facts(id) ON DELETE SET NULL,
    due_date        DATE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    notes           TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wi_client_status ON work_items(client_id, status);
CREATE INDEX IF NOT EXISTS idx_wi_assignee ON work_items(assignee, status);
