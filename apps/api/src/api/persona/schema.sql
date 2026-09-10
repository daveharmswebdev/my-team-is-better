-- issue #4 §4.1's Postgres response cache. A single additive table --
-- deliberately no migration framework (Alembic etc.), mirroring
-- packages/cfb-engine/src/cfb_strength/db/schema.sql's own plain-SQL,
-- ensure_schema()-applied approach for the same reason: this project's
-- stated philosophy is no premature abstraction.
CREATE TABLE IF NOT EXISTS persona_cache (
    cache_key TEXT PRIMARY KEY,
    narration_text TEXT NOT NULL,
    contested BOOLEAN NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
