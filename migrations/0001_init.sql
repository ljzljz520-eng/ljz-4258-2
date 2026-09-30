-- 乳脂分离与回配核算平台：初始 schema (PostgreSQL >= 13)
BEGIN;

CREATE TABLE IF NOT EXISTS topologies (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(64) UNIQUE NOT NULL,
    name        VARCHAR(200) NOT NULL,
    definition  JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batches (
    id          BIGSERIAL PRIMARY KEY,
    topology_id BIGINT NOT NULL REFERENCES topologies(id),
    code        VARCHAR(64) UNIQUE NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_batches_topology ON batches(topology_id);

CREATE TABLE IF NOT EXISTS segments (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT NOT NULL REFERENCES batches(id),
    seq           INTEGER NOT NULL,
    code          VARCHAR(64) NOT NULL,
    start_ts      TIMESTAMPTZ NOT NULL,
    end_ts        TIMESTAMPTZ NOT NULL,
    boundary_note TEXT NOT NULL DEFAULT '',
    CONSTRAINT uq_segment_code UNIQUE (batch_id, code)
);
CREATE INDEX IF NOT EXISTS ix_segments_batch ON segments(batch_id);

CREATE TABLE IF NOT EXISTS windows (
    id                   BIGSERIAL PRIMARY KEY,
    batch_id             BIGINT NOT NULL REFERENCES batches(id),
    label                VARCHAR(120) NOT NULL,
    segment_ids          JSONB NOT NULL,
    max_gap_s            DOUBLE PRECISION NOT NULL DEFAULT 900,
    extrap_tolerance_s   DOUBLE PRECISION NOT NULL DEFAULT 30,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_by        BIGINT REFERENCES windows(id)
);
CREATE INDEX IF NOT EXISTS ix_windows_batch ON windows(batch_id);

CREATE TABLE IF NOT EXISTS measurement_ranges (
    id          BIGSERIAL PRIMARY KEY,
    stream_id   VARCHAR(64) NOT NULL,
    metric      VARCHAR(32) NOT NULL,
    unit        VARCHAR(32) NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    active_from TIMESTAMPTZ,
    active_to   TIMESTAMPTZ,
    label       VARCHAR(120) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_ranges_stream ON measurement_ranges(stream_id);

CREATE TABLE IF NOT EXISTS tank_inventories (
    id               BIGSERIAL PRIMARY KEY,
    node_id          VARCHAR(64) NOT NULL,
    batch_id         BIGINT NOT NULL REFERENCES batches(id),
    segment_id       BIGINT REFERENCES segments(id),
    kind             VARCHAR(16) NOT NULL,
    mass_kg          DOUBLE PRECISION NOT NULL,
    fat_fraction_wet DOUBLE PRECISION NOT NULL,
    fat_mass_kg      DOUBLE PRECISION,
    abs_uc_mass      DOUBLE PRECISION,
    rel_uc_mass      DOUBLE PRECISION,
    ts               TIMESTAMPTZ NOT NULL,
    cross_batch      BOOLEAN NOT NULL DEFAULT FALSE,
    note             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_inv_node ON tank_inventories(node_id);
CREATE INDEX IF NOT EXISTS ix_inv_batch ON tank_inventories(batch_id);

CREATE TABLE IF NOT EXISTS samples (
    id                   BIGSERIAL PRIMARY KEY,
    stream_id            VARCHAR(64) NOT NULL,
    segment_id           BIGINT REFERENCES segments(id),
    ts                   TIMESTAMPTZ NOT NULL,
    metric               VARCHAR(32) NOT NULL,
    value                DOUBLE PRECISION NOT NULL,
    unit                 VARCHAR(32) NOT NULL,
    abs_uc               DOUBLE PRECISION,
    rel_uc               DOUBLE PRECISION,
    range_id             BIGINT REFERENCES measurement_ranges(id),
    solids_fraction_wet  DOUBLE PRECISION,
    received_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_sample_id BIGINT
);
CREATE INDEX IF NOT EXISTS ix_samples_stream ON samples(stream_id);
CREATE INDEX IF NOT EXISTS ix_samples_segment ON samples(segment_id);
CREATE INDEX IF NOT EXISTS ix_samples_ts ON samples(ts);

CREATE TABLE IF NOT EXISTS calc_versions (
    id         BIGSERIAL PRIMARY KEY,
    version    VARCHAR(32) UNIQUE NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id                BIGSERIAL PRIMARY KEY,
    window_id         BIGINT NOT NULL REFERENCES windows(id),
    status            VARCHAR(16) NOT NULL DEFAULT 'queued',
    input_digest      VARCHAR(64) NOT NULL,
    input_snapshot    JSONB NOT NULL,
    algorithm_version VARCHAR(32) NOT NULL,
    queued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    locked_by         VARCHAR(64),
    error             TEXT NOT NULL DEFAULT '',
    is_current        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_jobs_window ON jobs(window_id);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS ix_jobs_digest ON jobs(input_digest);
CREATE INDEX IF NOT EXISTS ix_jobs_current ON jobs(is_current);

CREATE TABLE IF NOT EXISTS results (
    id                BIGSERIAL PRIMARY KEY,
    job_id            BIGINT NOT NULL REFERENCES jobs(id),
    window_id         BIGINT NOT NULL REFERENCES windows(id),
    digest            VARCHAR(64) NOT NULL,
    algorithm_version VARCHAR(32) NOT NULL,
    status            VARCHAR(24) NOT NULL,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    payload           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_results_job ON results(job_id);
CREATE INDEX IF NOT EXISTS ix_results_window ON results(window_id);
CREATE INDEX IF NOT EXISTS ix_results_digest ON results(digest);
CREATE INDEX IF NOT EXISTS ix_results_current ON results(is_current);

CREATE TABLE IF NOT EXISTS signoffs (
    id                BIGSERIAL PRIMARY KEY,
    window_id         BIGINT NOT NULL REFERENCES windows(id),
    result_id         BIGINT NOT NULL REFERENCES results(id),
    engineer          VARCHAR(120) NOT NULL,
    input_digest      VARCHAR(64) NOT NULL,
    algorithm_version VARCHAR(32) NOT NULL,
    input_summary     JSONB NOT NULL,
    note              TEXT NOT NULL DEFAULT '',
    revoked           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_signoffs_window ON signoffs(window_id);
CREATE INDEX IF NOT EXISTS ix_signoffs_revoked ON signoffs(revoked);

CREATE TABLE IF NOT EXISTS signoff_events (
    id          BIGSERIAL PRIMARY KEY,
    signoff_id  BIGINT NOT NULL REFERENCES signoffs(id),
    kind        VARCHAR(32) NOT NULL,
    actor       VARCHAR(120) NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_signoff_events_signoff ON signoff_events(signoff_id);

COMMIT;
