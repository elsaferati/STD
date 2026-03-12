-- Add PX control permissions and super-admin flag to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_control_1 BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_control_2 BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_final_control BOOLEAN NOT NULL DEFAULT FALSE;

-- PX control tracking table (one row per order)
CREATE TABLE IF NOT EXISTS order_px_controls (
    order_id UUID PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    px_status TEXT NOT NULL DEFAULT 'pending',
    control_1_user_id UUID REFERENCES users(id),
    control_1_at TIMESTAMPTZ,
    control_2_user_id UUID REFERENCES users(id),
    control_2_at TIMESTAMPTZ,
    final_control_user_id UUID REFERENCES users(id),
    final_control_at TIMESTAMPTZ,
    xml_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Back-fill existing orders that don't yet have a PX controls row
INSERT INTO order_px_controls (order_id)
SELECT id FROM orders
WHERE deleted_at IS NULL
ON CONFLICT (order_id) DO NOTHING;
