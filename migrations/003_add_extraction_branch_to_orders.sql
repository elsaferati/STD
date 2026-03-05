ALTER TABLE orders
ADD COLUMN IF NOT EXISTS extraction_branch TEXT;

WITH revision_branch AS (
    SELECT o.id AS order_id,
           LOWER(BTRIM(COALESCE(r.payload_json ->> 'extraction_branch', ''))) AS branch_id
    FROM orders o
    JOIN order_revisions r ON r.id = o.current_revision_id
)
UPDATE orders o
SET extraction_branch = CASE
    WHEN rb.branch_id IN ('xxxlutz_default', 'momax_bg', 'porta', 'braun', 'segmuller') THEN rb.branch_id
    ELSE 'unknown'
END
FROM revision_branch rb
WHERE o.id = rb.order_id;

UPDATE orders
SET extraction_branch = 'unknown'
WHERE extraction_branch IS NULL
   OR BTRIM(extraction_branch) = ''
   OR LOWER(BTRIM(extraction_branch)) NOT IN ('xxxlutz_default', 'momax_bg', 'porta', 'braun', 'segmuller', 'unknown');

UPDATE orders
SET extraction_branch = LOWER(BTRIM(extraction_branch))
WHERE extraction_branch <> LOWER(BTRIM(extraction_branch));

ALTER TABLE orders
ALTER COLUMN extraction_branch SET DEFAULT 'unknown';

UPDATE orders
SET extraction_branch = 'unknown'
WHERE extraction_branch IS NULL;

ALTER TABLE orders
ALTER COLUMN extraction_branch SET NOT NULL;

CREATE INDEX IF NOT EXISTS orders_extraction_branch_received_at_idx
    ON orders (extraction_branch, received_at DESC);
