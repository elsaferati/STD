CREATE TABLE IF NOT EXISTS modelnr_anonym_mapping (
    intern TEXT NOT NULL DEFAULT '',
    anonym TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS modelnr_anonym_mapping_anonym_idx
    ON modelnr_anonym_mapping (anonym);

CREATE INDEX IF NOT EXISTS modelnr_anonym_mapping_intern_idx
    ON modelnr_anonym_mapping (intern);
