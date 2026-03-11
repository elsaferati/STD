ALTER TABLE delivery_preparation_rules
    ADD COLUMN IF NOT EXISTS year_from INTEGER,
    ADD COLUMN IF NOT EXISTS year_to INTEGER;

UPDATE delivery_preparation_rules
SET year_from = EXTRACT(ISOYEAR FROM CURRENT_DATE)::INTEGER,
    year_to = EXTRACT(ISOYEAR FROM CURRENT_DATE)::INTEGER
WHERE NOT is_default
  AND year_from IS NULL
  AND year_to IS NULL;

ALTER TABLE delivery_preparation_rules
    DROP CONSTRAINT IF EXISTS delivery_preparation_rules_no_overlap;

DROP INDEX IF EXISTS delivery_preparation_rules_week_bounds_idx;

ALTER TABLE delivery_preparation_rules
    DROP CONSTRAINT IF EXISTS delivery_preparation_rules_shape_chk;

ALTER TABLE delivery_preparation_rules
    ADD CONSTRAINT delivery_preparation_rules_shape_chk CHECK (
        (
            is_default
            AND year_from IS NULL
            AND week_from IS NULL
            AND year_to IS NULL
            AND week_to IS NULL
        )
        OR (
            NOT is_default
            AND year_from IS NOT NULL
            AND week_from IS NOT NULL
            AND year_to IS NOT NULL
            AND week_to IS NOT NULL
            AND year_from BETWEEN 1900 AND 9999
            AND year_to BETWEEN 1900 AND 9999
            AND week_from BETWEEN 1 AND 53
            AND week_to BETWEEN 1 AND 53
            AND (
                year_from < year_to
                OR (year_from = year_to AND week_from <= week_to)
            )
        )
    );

CREATE INDEX IF NOT EXISTS delivery_preparation_rules_year_week_bounds_idx
    ON delivery_preparation_rules (year_from, week_from, year_to, week_to)
    WHERE NOT is_default;
