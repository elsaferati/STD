CREATE INDEX IF NOT EXISTS orders_effective_received_at_active_idx
    ON orders ((COALESCE(received_at, updated_at)) DESC)
    WHERE deleted_at IS NULL;
