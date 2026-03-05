CREATE TABLE IF NOT EXISTS user_client_scopes (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, branch_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'user_client_scopes'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE user_client_scopes
            ADD CONSTRAINT user_client_scopes_pkey PRIMARY KEY (user_id, branch_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS user_client_scopes_user_id_idx ON user_client_scopes (user_id);
CREATE INDEX IF NOT EXISTS user_client_scopes_branch_id_idx ON user_client_scopes (branch_id);

DELETE FROM user_client_scopes ucs
USING users u
WHERE ucs.user_id = u.id
  AND LOWER(BTRIM(COALESCE(u.role, ''))) <> 'admin';
