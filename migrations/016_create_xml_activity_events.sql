CREATE TABLE IF NOT EXISTS xml_activity_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id_snapshot TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    file_count INTEGER NOT NULL CHECK (file_count > 0),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL DEFAULT '',
    source_ref TEXT,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS xml_activity_events_occurred_at_idx
    ON xml_activity_events (occurred_at DESC);

CREATE INDEX IF NOT EXISTS xml_activity_events_event_type_occurred_at_idx
    ON xml_activity_events (event_type, occurred_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS xml_activity_events_source_ref_uidx
    ON xml_activity_events (source_ref)
    WHERE source_ref IS NOT NULL;

INSERT INTO xml_activity_events (
    id,
    order_id_snapshot,
    event_type,
    file_count,
    occurred_at,
    source,
    source_ref,
    actor_user_id,
    metadata_json,
    created_at
)
SELECT
    gen_random_uuid(),
    px.order_id::text,
    'xml_generated_after_final_control',
    2,
    px.xml_sent_at,
    'backfill_px_xml_sent',
    'px_xml_sent:' || px.order_id::text || ':' || to_char(px.xml_sent_at AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS.US'),
    NULL,
    jsonb_build_object('backfilled_from', 'order_px_controls'),
    now()
FROM order_px_controls px
WHERE px.xml_sent_at IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO xml_activity_events (
    id,
    order_id_snapshot,
    event_type,
    file_count,
    occurred_at,
    source,
    source_ref,
    actor_user_id,
    metadata_json,
    created_at
)
SELECT
    gen_random_uuid(),
    e.order_id::text,
    CASE
        WHEN e.event_type = 'xml_regenerated' THEN 'xml_regenerated_both'
        WHEN e.event_type = 'order_xml_regenerated' THEN 'xml_regenerated_order_only'
        WHEN e.event_type = 'article_xml_regenerated' THEN 'xml_regenerated_article_only'
    END,
    CASE
        WHEN e.event_type = 'xml_regenerated' THEN 2
        ELSE 1
    END,
    e.created_at,
    'backfill_order_events',
    'order_event:' || e.id::text,
    e.actor_user_id,
    jsonb_build_object(
        'backfilled_from', 'order_events',
        'original_event_id', e.id,
        'original_event_type', e.event_type
    ),
    now()
FROM order_events e
WHERE e.event_type IN ('xml_regenerated', 'order_xml_regenerated', 'article_xml_regenerated')
ON CONFLICT DO NOTHING;
