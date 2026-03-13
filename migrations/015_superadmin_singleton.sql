UPDATE users
SET role = CASE
    WHEN COALESCE(is_super_admin, FALSE) IS TRUE THEN 'admin'
    WHEN LOWER(BTRIM(COALESCE(role, ''))) = 'superadmin' THEN 'admin'
    WHEN LOWER(BTRIM(COALESCE(role, ''))) IN ('user', 'admin') THEN LOWER(BTRIM(COALESCE(role, '')))
    ELSE 'user'
END;

UPDATE users
SET is_super_admin = FALSE
WHERE COALESCE(is_super_admin, FALSE) IS TRUE;

DELETE FROM user_client_scopes ucs
USING users u
WHERE ucs.user_id = u.id
  AND LOWER(BTRIM(COALESCE(u.role, ''))) IN ('admin', 'superadmin');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'users'::regclass
          AND conname = 'users_role_valid_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_role_valid_check
            CHECK (LOWER(BTRIM(COALESCE(role, ''))) IN ('user', 'admin', 'superadmin'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_superadmin_singleton_idx
    ON users (role)
    WHERE LOWER(BTRIM(COALESCE(role, ''))) = 'superadmin';
