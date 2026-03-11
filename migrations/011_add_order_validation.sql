ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'not_run',
    ADD COLUMN IF NOT EXISTS validation_summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS validation_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS validation_model TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS validation_stale_reason TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS order_validation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    revision_id UUID NOT NULL REFERENCES order_revisions(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    issues_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, revision_id, provider)
);

CREATE INDEX IF NOT EXISTS orders_validation_status_idx ON orders (validation_status);
CREATE INDEX IF NOT EXISTS orders_validation_checked_at_idx ON orders (validation_checked_at DESC);
CREATE INDEX IF NOT EXISTS order_validation_runs_order_created_idx ON order_validation_runs (order_id, created_at DESC);
