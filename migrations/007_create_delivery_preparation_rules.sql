CREATE TABLE IF NOT EXISTS delivery_preparation_rules (
    id BIGSERIAL PRIMARY KEY,
    week_from SMALLINT,
    week_to SMALLINT,
    prep_weeks INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT delivery_preparation_rules_shape_chk CHECK (
        (
            is_default
            AND week_from IS NULL
            AND week_to IS NULL
        )
        OR (
            NOT is_default
            AND week_from IS NOT NULL
            AND week_to IS NOT NULL
            AND week_from BETWEEN 1 AND 52
            AND week_to BETWEEN 1 AND 52
            AND week_from <= week_to
        )
    ),
    CONSTRAINT delivery_preparation_rules_prep_weeks_chk CHECK (prep_weeks >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS delivery_preparation_rules_single_default_idx
    ON delivery_preparation_rules (is_default)
    WHERE is_default;

CREATE INDEX IF NOT EXISTS delivery_preparation_rules_week_bounds_idx
    ON delivery_preparation_rules (week_from, week_to)
    WHERE NOT is_default;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'delivery_preparation_rules_no_overlap'
    ) THEN
        ALTER TABLE delivery_preparation_rules
            ADD CONSTRAINT delivery_preparation_rules_no_overlap
            EXCLUDE USING gist (
                int4range(week_from, week_to, '[]') WITH &&
            )
            WHERE (NOT is_default);
    END IF;
END $$;

INSERT INTO delivery_preparation_rules (week_from, week_to, prep_weeks, is_default)
SELECT NULL, NULL, 2, TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM delivery_preparation_rules
    WHERE is_default
);
