-- ===========================================================================
-- 0001_init - first ordered migration of the SPECTRA 1.0.0 stream.
--
-- Target: control plane database.
-- Applied on every deploy (the runner skips files already recorded in
-- spectra_schema_history), so it must be idempotent.
--
-- The greenfield schema lives in db/baseline/001_control_plane.sql.  This file
-- anchors the append-only migration stream and adds the release log that
-- show-state.sh and verify-deployment.sh read back.
-- ===========================================================================

-- spectra:target=control

BEGIN;

CREATE TABLE IF NOT EXISTS spectra_release_log (
    app_version text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    note        text
);

COMMENT ON TABLE spectra_release_log IS
    'One row per SPECTRA release whose migrations have been applied to this database.';

INSERT INTO spectra_release_log (app_version, note)
VALUES ('1.0.0', 'initial control-plane schema')
ON CONFLICT (app_version) DO NOTHING;

COMMIT;
