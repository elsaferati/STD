CREATE TABLE IF NOT EXISTS modelnr_std_import_stage (
    vabtra TEXT NOT NULL DEFAULT '',
    vamdnr TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS modelnr_std_import_stage_vamdnr_idx
    ON modelnr_std_import_stage (vamdnr);
