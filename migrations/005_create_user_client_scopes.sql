CREATE TABLE IF NOT EXISTS user_client_scopes (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, branch_id)
);

CREATE INDEX IF NOT EXISTS user_client_scopes_user_id_idx ON user_client_scopes (user_id);
CREATE INDEX IF NOT EXISTS user_client_scopes_branch_id_idx ON user_client_scopes (branch_id);

INSERT INTO user_client_scopes (user_id, branch_id, created_at)
SELECT u.id, branches.branch_id, now()
FROM users u
CROSS JOIN (
    VALUES
        ('xxxlutz_default'),
        ('momax_bg'),
        ('porta'),
        ('braun'),
        ('segmuller'),
        ('unknown')
) AS branches(branch_id)
WHERE LOWER(BTRIM(COALESCE(u.role, ''))) <> 'admin'
ON CONFLICT (user_id, branch_id) DO NOTHING;
