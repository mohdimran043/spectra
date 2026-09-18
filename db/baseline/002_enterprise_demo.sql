-- ===========================================================================
-- SPECTRA enterprise demo - greenfield baseline.
--
-- Target database: ${ENTERPRISE_DB} (default `spectra_enterprise`), schema
-- `enterprise`.  This is deliberately a SEPARATE database from the SPECTRA
-- control plane: "query a real business database" must be a genuine external
-- source path for the Database Agent, not a privileged internal shortcut.
--
-- Also creates the SELECT-only role the Database Agent and the mock enterprise
-- application connect as.  That role can read the `enterprise` schema and
-- nothing else - no writes, no DDL, no other schema.
--
-- psql variables (scripts/run-migrations.sh supplies all of them):
--   -v readonly_user=spectra_readonly
--   -v readonly_password=<secret>
--   -v owner_role=spectra
--   -v statement_timeout=10s
-- ===========================================================================

-- spectra:target=enterprise

\if :{?readonly_user}
\else
\set readonly_user 'spectra_readonly'
\endif

\if :{?owner_role}
\else
\set owner_role 'spectra'
\endif

\if :{?statement_timeout}
\else
\set statement_timeout '10s'
\endif

\if :{?readonly_password}
\else
\set readonly_password ''
\endif

SELECT CASE WHEN coalesce(:'readonly_password', '') <> '' THEN 'true' ELSE 'false' END AS has_readonly_password \gset

\if :has_readonly_password
\else
DO $guard$
BEGIN
    RAISE EXCEPTION 'readonly_password is required: rerun with psql -v readonly_password=...';
END
$guard$;
\endif

BEGIN;

CREATE SCHEMA IF NOT EXISTS enterprise;

-- ---------------------------------------------------------------------------
-- customers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise.customers (
    customer_id      text PRIMARY KEY,                 -- e.g. C82731
    legal_name       text        NOT NULL,
    display_name     text        NOT NULL,
    segment          text        NOT NULL DEFAULT 'retail'
        CHECK (segment IN ('retail', 'sme', 'corporate', 'government', 'internal')),
    status           text        NOT NULL DEFAULT 'active'
        CHECK (status IN ('prospect', 'active', 'suspended', 'closed')),
    tier             text        NOT NULL DEFAULT 'standard'
        CHECK (tier IN ('standard', 'silver', 'gold', 'platinum')),
    email            text,
    phone            text,
    address_line1    text,
    address_line2    text,
    city             text,
    postal_code      text,
    country_code     char(2)     NOT NULL DEFAULT 'GB',
    account_manager  text,
    kyc_status       text        NOT NULL DEFAULT 'pending'
        CHECK (kyc_status IN ('pending', 'verified', 'review', 'rejected')),
    risk_score       numeric(5, 2) NOT NULL DEFAULT 0.00
        CHECK (risk_score >= 0 AND risk_score <= 100),
    onboarded_at     timestamptz,
    closed_at        timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_customers_status  ON enterprise.customers (status);
CREATE INDEX IF NOT EXISTS idx_customers_segment ON enterprise.customers (segment);
CREATE INDEX IF NOT EXISTS idx_customers_name    ON enterprise.customers (lower(display_name));
CREATE INDEX IF NOT EXISTS idx_customers_email   ON enterprise.customers (lower(email));

-- ---------------------------------------------------------------------------
-- assets (physical and logical business assets - not SPECTRA's ingested assets)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise.assets (
    asset_id            text PRIMARY KEY,             -- e.g. AST-00317
    name                text        NOT NULL,
    asset_type          text        NOT NULL
        CHECK (asset_type IN ('vehicle', 'machine', 'server', 'camera', 'terminal', 'building')),
    serial_number       text UNIQUE,
    manufacturer        text,
    model               text,
    site                text        NOT NULL DEFAULT 'unknown',
    location_detail     text,
    status              text        NOT NULL DEFAULT 'in_service'
        CHECK (status IN ('in_service', 'maintenance', 'decommissioned', 'missing')),
    owner_customer_id   text        REFERENCES enterprise.customers (customer_id) ON DELETE SET NULL,
    commissioned_at     date,
    last_serviced_at    date,
    warranty_expires_at date,
    metadata            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assets_site   ON enterprise.assets (site);
CREATE INDEX IF NOT EXISTS idx_assets_type   ON enterprise.assets (asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_status ON enterprise.assets (status);
CREATE INDEX IF NOT EXISTS idx_assets_owner  ON enterprise.assets (owner_customer_id);

-- ---------------------------------------------------------------------------
-- transactions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise.transactions (
    transaction_id       text PRIMARY KEY,            -- e.g. TX82931
    customer_id          text        NOT NULL REFERENCES enterprise.customers (customer_id) ON DELETE RESTRICT,
    occurred_at          timestamptz NOT NULL,
    posted_at            timestamptz,
    amount               numeric(18, 2) NOT NULL,
    currency             char(3)     NOT NULL DEFAULT 'GBP',
    direction            text        NOT NULL CHECK (direction IN ('debit', 'credit')),
    channel              text        NOT NULL DEFAULT 'web'
        CHECK (channel IN ('web', 'mobile', 'branch', 'atm', 'api', 'wire')),
    status               text        NOT NULL DEFAULT 'settled'
        CHECK (status IN ('pending', 'settled', 'reversed', 'failed', 'flagged')),
    counterparty_name    text,
    counterparty_account text,
    merchant_category    text,
    reference            text,
    description          text,
    risk_flags           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transactions_customer ON enterprise.transactions (customer_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_occurred ON enterprise.transactions (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_status   ON enterprise.transactions (status);
CREATE INDEX IF NOT EXISTS idx_transactions_flagged  ON enterprise.transactions (occurred_at DESC)
    WHERE status = 'flagged';

-- ---------------------------------------------------------------------------
-- incidents - the join point between customers, assets and transactions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise.incidents (
    incident_id        text PRIMARY KEY,              -- e.g. INC-2026-0042
    title              text        NOT NULL,
    description        text,
    category           text        NOT NULL DEFAULT 'quality'
        CHECK (category IN ('fraud', 'outage', 'security', 'compliance', 'safety', 'quality')),
    severity           text        NOT NULL DEFAULT 'medium'
        CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    status             text        NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'triage', 'investigating', 'mitigated', 'resolved', 'closed')),
    customer_id        text        REFERENCES enterprise.customers    (customer_id)    ON DELETE SET NULL,
    asset_id           text        REFERENCES enterprise.assets       (asset_id)       ON DELETE SET NULL,
    transaction_id     text        REFERENCES enterprise.transactions (transaction_id) ON DELETE SET NULL,
    site               text,
    reported_by        text,
    assigned_to        text,
    reported_at        timestamptz NOT NULL DEFAULT now(),
    acknowledged_at    timestamptz,
    resolved_at        timestamptz,
    resolution_summary text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidents_customer ON enterprise.incidents (customer_id);
CREATE INDEX IF NOT EXISTS idx_incidents_asset    ON enterprise.incidents (asset_id);
CREATE INDEX IF NOT EXISTS idx_incidents_txn      ON enterprise.incidents (transaction_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status   ON enterprise.incidents (status, severity);
CREATE INDEX IF NOT EXISTS idx_incidents_reported ON enterprise.incidents (reported_at DESC);

-- ---------------------------------------------------------------------------
-- A minimal, self-consistent demo dataset so a fresh install is never empty.
-- `make seed-demo` loads the full corpus on top of this.
-- ---------------------------------------------------------------------------
INSERT INTO enterprise.customers
    (customer_id, legal_name, display_name, segment, status, tier, email, city, country_code,
     account_manager, kyc_status, risk_score, onboarded_at)
VALUES
    ('C82731', 'Halden Logistics Ltd',  'Halden Logistics',  'corporate',  'active',    'gold',     'ops@halden.example',           'Leeds',      'GB', 'r.okafor',  'verified', 41.50, '2023-02-14T09:00:00Z'),
    ('C90114', 'Brightwater Foods PLC', 'Brightwater Foods', 'corporate',  'active',    'platinum', 'finance@bwf.example',          'Bristol',    'GB', 'r.okafor',  'verified', 12.25, '2021-11-02T09:00:00Z'),
    ('C77402', 'Marek Sobczak',         'M. Sobczak',        'retail',     'active',    'standard', 'm.sobczak@mail.example',       'Manchester', 'GB', 'a.ferreira','verified',  8.00, '2024-06-21T09:00:00Z'),
    ('C65008', 'Northgate Clinics Ltd', 'Northgate Clinics', 'sme',        'suspended', 'silver',   'admin@northgate.example',      'Glasgow',    'GB', 'a.ferreira','review',   73.80, '2022-08-30T09:00:00Z'),
    ('C51993', 'City of Aldermere',     'Aldermere Council', 'government', 'active',    'gold',     'procurement@aldermere.example','Aldermere',  'GB', 'j.hall',    'verified',  5.10, '2020-04-06T09:00:00Z')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO enterprise.assets
    (asset_id, name, asset_type, serial_number, manufacturer, model, site, location_detail,
     status, owner_customer_id, commissioned_at, last_serviced_at, warranty_expires_at)
VALUES
    ('AST-00317', 'Loading bay camera 3', 'camera',   'SN-CAM-00317', 'Vistek',  'VX-900',  'Leeds DC',       'Bay 3, north wall', 'in_service',     'C82731', '2023-03-01', '2026-06-12', '2027-03-01'),
    ('AST-00412', 'Reefer trailer 12',    'vehicle',  'SN-VEH-00412', 'Frigora', 'RT-12',   'Leeds DC',       'Yard slot 12',      'maintenance',    'C82731', '2022-09-15', '2026-08-30', '2026-09-15'),
    ('AST-00088', 'Cold store chiller A', 'machine',  'SN-MCH-00088', 'Polaris', 'CS-4000', 'Bristol Plant',  'Cold store A',      'in_service',     'C90114', '2021-12-05', '2026-07-19', '2026-12-05'),
    ('AST-00521', 'POS terminal 7',       'terminal', 'SN-TRM-00521', 'Paylink', 'PT-7',    'Glasgow Clinic', 'Reception desk',    'decommissioned', 'C65008', '2022-10-10', '2025-11-04', '2025-10-10')
ON CONFLICT (asset_id) DO NOTHING;

INSERT INTO enterprise.transactions
    (transaction_id, customer_id, occurred_at, posted_at, amount, currency, direction, channel,
     status, counterparty_name, merchant_category, reference, description, risk_flags)
VALUES
    ('TX82931', 'C82731', '2026-08-30T14:22:00Z', '2026-08-30T14:25:00Z', 48250.00, 'GBP', 'debit',  'wire',   'flagged',  'Sunhill Freight SA', 'freight',   'PO-4471',  'Freight settlement, August',          '["unusual_amount","new_counterparty"]'),
    ('TX82944', 'C82731', '2026-08-31T09:05:00Z', '2026-08-31T09:06:00Z',  1120.40, 'GBP', 'debit',  'api',    'settled',  'Fuelcard Ltd',       'fuel',      'PO-4472',  'Fleet fuel card, week 35',            '[]'),
    ('TX91330', 'C90114', '2026-09-01T11:47:00Z', '2026-09-01T11:48:00Z', 98500.00, 'GBP', 'credit', 'branch', 'settled',  'Aldermere Council',  'wholesale', 'INV-2291', 'Q3 wholesale invoice payment',        '[]'),
    ('TX77510', 'C77402', '2026-09-02T19:12:00Z', NULL,                     219.99, 'GBP', 'debit',  'mobile', 'pending',  'Marketplace UK',     'retail',    NULL,       'Marketplace order 88-2210',           '[]'),
    ('TX65221', 'C65008', '2026-09-03T08:30:00Z', '2026-09-03T08:31:00Z',  4300.00, 'GBP', 'debit',  'web',    'reversed', 'Medsupply Direct',   'medical',   'PO-1188',  'Consumables order, reversed by bank', '["reversal"]'),
    ('TX51007', 'C51993', '2026-09-04T13:00:00Z', '2026-09-04T13:02:00Z', 15750.00, 'GBP', 'credit', 'wire',   'settled',  'Brightwater Foods',  'wholesale', 'INV-2294', 'Catering framework, September',       '[]')
ON CONFLICT (transaction_id) DO NOTHING;

INSERT INTO enterprise.incidents
    (incident_id, title, description, category, severity, status, customer_id, asset_id,
     transaction_id, site, reported_by, assigned_to, reported_at, acknowledged_at, resolved_at, resolution_summary)
VALUES
    ('INC-2026-0042', 'Unexplained freight settlement',        'Payment to a counterparty with no matching purchase order; camera footage requested for the same loading bay and time window.', 'fraud',      'high',     'investigating', 'C82731', 'AST-00317', 'TX82931', 'Leeds DC',       'k.mensah',  'f.dubois', '2026-08-31T07:40:00Z', '2026-08-31T08:05:00Z', NULL, NULL),
    ('INC-2026-0051', 'Reefer trailer temperature excursion',  'Trailer 12 logged +6C for 40 minutes during the Bristol run.',                                                                  'quality',    'medium',   'mitigated',     'C82731', 'AST-00412', NULL,      'Leeds DC',       'd.arnold',  'f.dubois', '2026-09-01T16:10:00Z', '2026-09-01T16:22:00Z', NULL, 'Trailer pulled from service pending compressor check.'),
    ('INC-2026-0063', 'Chiller A compressor alarm',            'Repeating high-pressure alarm on cold store chiller A.',                                                                        'safety',     'critical', 'open',          'C90114', 'AST-00088', NULL,      'Bristol Plant',  's.iqbal',   NULL,       '2026-09-03T05:12:00Z', NULL,                   NULL, NULL),
    ('INC-2026-0070', 'Reversed consumables payment',          'Bank reversed a consumables payment while the account is under KYC review.',                                                    'compliance', 'high',     'triage',        'C65008', 'AST-00521', 'TX65221', 'Glasgow Clinic', 'a.ferreira','j.hall',   '2026-09-03T10:02:00Z', '2026-09-03T10:30:00Z', NULL, NULL)
ON CONFLICT (incident_id) DO NOTHING;

COMMIT;

-- ===========================================================================
-- Read-only role.  This is the identity the SPECTRA Database Agent uses, so it
-- must never be able to change anything.  It gets SELECT on the enterprise
-- schema and nothing else, with read-only transactions and a statement timeout
-- enforced at the role level.
-- ===========================================================================

SELECT format('CREATE ROLE %I NOLOGIN', :'readonly_user')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'readonly_user')
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'readonly_user', :'readonly_password')
\gexec

-- Read-only by default and bounded: a runaway agent query cannot pin a backend.
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'readonly_user')
\gexec

SELECT format('ALTER ROLE %I SET statement_timeout = %L', :'readonly_user', :'statement_timeout')
\gexec

SELECT format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', :'readonly_user', '30s')
\gexec

-- No accidental object creation anywhere in this database.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database())
\gexec

SELECT 'REVOKE CREATE ON SCHEMA public FROM PUBLIC'
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'readonly_user')
\gexec

SELECT format('GRANT USAGE ON SCHEMA enterprise TO %I', :'readonly_user')
\gexec

SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA enterprise TO %I', :'readonly_user')
\gexec

-- Tables added by later migrations inherit the same SELECT-only grant.
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA enterprise GRANT SELECT ON TABLES TO %I',
              :'owner_role', :'readonly_user')
\gexec

-- Belt and braces: make the absence of write privileges explicit.
SELECT format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA enterprise FROM %I',
              :'readonly_user')
\gexec

SELECT format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA enterprise FROM %I', :'readonly_user')
\gexec
