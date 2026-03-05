CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_message_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    received_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'ok',
    reply_needed BOOLEAN NOT NULL DEFAULT FALSE,
    human_review_needed BOOLEAN NOT NULL DEFAULT FALSE,
    post_case BOOLEAN NOT NULL DEFAULT FALSE,
    ticket_number TEXT NOT NULL DEFAULT '',
    kundennummer TEXT NOT NULL DEFAULT '',
    kom_nr TEXT NOT NULL DEFAULT '',
    kom_name TEXT NOT NULL DEFAULT '',
    liefertermin TEXT NOT NULL DEFAULT '',
    wunschtermin TEXT NOT NULL DEFAULT '',
    delivery_week TEXT NOT NULL DEFAULT '',
    store_name TEXT NOT NULL DEFAULT '',
    store_address TEXT NOT NULL DEFAULT '',
    iln TEXT NOT NULL DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    parse_error TEXT,
    current_revision_id UUID,
    current_revision_no INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS order_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    changed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    payload_json JSONB NOT NULL,
    diff_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, revision_no)
);

CREATE TABLE IF NOT EXISTS order_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    revision_id UUID NOT NULL REFERENCES order_revisions(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    code TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_items_current (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    artikelnummer TEXT NOT NULL DEFAULT '',
    modellnummer TEXT NOT NULL DEFAULT '',
    menge NUMERIC(12,3),
    furncloud_id TEXT NOT NULL DEFAULT '',
    field_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, line_no)
);

CREATE TABLE IF NOT EXISTS order_review_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    state TEXT NOT NULL,
    priority SMALLINT NOT NULL DEFAULT 5,
    assigned_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    claimed_at TIMESTAMPTZ,
    claim_expires_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolution_outcome TEXT,
    resolution_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    revision_id UUID REFERENCES order_revisions(id) ON DELETE SET NULL,
    file_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_events (
    id BIGSERIAL PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    revision_id UUID REFERENCES order_revisions(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'orders_current_revision_fk'
          AND table_name = 'orders'
    ) THEN
        ALTER TABLE orders
        ADD CONSTRAINT orders_current_revision_fk
        FOREIGN KEY (current_revision_id)
        REFERENCES order_revisions(id)
        ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS orders_status_received_at_idx ON orders (status, received_at DESC);
CREATE INDEX IF NOT EXISTS orders_received_at_idx ON orders (received_at DESC);
CREATE INDEX IF NOT EXISTS orders_flags_idx ON orders (reply_needed, human_review_needed, post_case);
CREATE INDEX IF NOT EXISTS orders_ticket_number_idx ON orders (ticket_number);
CREATE INDEX IF NOT EXISTS orders_kom_nr_idx ON orders (kom_nr);
CREATE INDEX IF NOT EXISTS orders_kom_name_idx ON orders (kom_name);
CREATE INDEX IF NOT EXISTS orders_deleted_at_idx ON orders (deleted_at);

CREATE INDEX IF NOT EXISTS order_review_tasks_state_due_at_idx ON order_review_tasks (state, due_at);
CREATE INDEX IF NOT EXISTS order_review_tasks_assigned_state_idx ON order_review_tasks (assigned_user_id, state);
CREATE INDEX IF NOT EXISTS order_review_tasks_order_id_idx ON order_review_tasks (order_id);
CREATE INDEX IF NOT EXISTS order_review_tasks_claim_expires_idx ON order_review_tasks (claim_expires_at);

CREATE INDEX IF NOT EXISTS order_revisions_order_revision_no_idx ON order_revisions (order_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS order_messages_order_active_idx ON order_messages (order_id, is_active);
CREATE INDEX IF NOT EXISTS order_items_current_order_line_idx ON order_items_current (order_id, line_no);
CREATE INDEX IF NOT EXISTS order_items_current_artikelnummer_idx ON order_items_current (artikelnummer);
CREATE INDEX IF NOT EXISTS order_items_current_modellnummer_idx ON order_items_current (modellnummer);
CREATE INDEX IF NOT EXISTS order_events_order_created_at_idx ON order_events (order_id, created_at DESC);
