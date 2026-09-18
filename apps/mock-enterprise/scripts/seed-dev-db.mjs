#!/usr/bin/env node
/**
 * DEVELOPMENT CONVENIENCE ONLY.
 *
 * Creates a small SQLite fixture at `data/runtime/enterprise.db` so the mock
 * enterprise application can be run before the real demo dataset exists. It is
 * NOT the demo data generator and it is NOT used at runtime: the application
 * always reads whatever database it is pointed at.
 *
 * It refuses to touch an existing file, so it can never overwrite the real
 * generated demo dataset.
 *
 *   node scripts/seed-dev-db.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import Database from 'better-sqlite3';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../../..');
const DEFAULT_DB_PATH = path.join(REPO_ROOT, 'data', 'runtime', 'enterprise.db');

const CUSTOMER_COUNT = 20;
const TRANSACTION_COUNT = 60;
const INCIDENT_COUNT = 8;
const ASSET_COUNT = 10;

/** Deterministic PRNG so repeated runs produce an identical fixture. */
function mulberry32(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const random = mulberry32(20260917);

const pick = (values) => values[Math.floor(random() * values.length)];
const between = (min, max) => min + random() * (max - min);

const SCHEMA = `
CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  email       TEXT NOT NULL,
  segment     TEXT,
  country     TEXT,
  risk_score  REAL,
  created_at  TEXT,
  status      TEXT
);
CREATE TABLE incidents (
  incident_id TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  severity    TEXT,
  status      TEXT,
  category    TEXT,
  root_cause  TEXT,
  service     TEXT,
  opened_at   TEXT,
  resolved_at TEXT,
  approved    INTEGER,
  approved_by TEXT
);
CREATE TABLE transactions (
  transaction_id TEXT PRIMARY KEY,
  customer_id    TEXT REFERENCES customers(customer_id),
  amount         REAL,
  currency       TEXT,
  status         TEXT,
  method         TEXT,
  failure_reason TEXT,
  created_at     TEXT,
  updated_at     TEXT,
  incident_id    TEXT REFERENCES incidents(incident_id)
);
CREATE TABLE assets (
  asset_id    TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT,
  owner       TEXT,
  environment TEXT,
  service     TEXT,
  status      TEXT,
  created_at  TEXT
);
CREATE INDEX idx_transactions_customer ON transactions(customer_id);
CREATE INDEX idx_transactions_incident ON transactions(incident_id);
CREATE INDEX idx_assets_service ON assets(service);
CREATE INDEX idx_incidents_service ON incidents(service);
`;

const SERVICES = [
  'payments-api',
  'auth-service',
  'ledger-db',
  'checkout-web',
  'notification-service',
];

const FIRST_NAMES = ['Mohammed', 'Aisha', 'Daniel', 'Priya', 'Lucas', 'Nadia', 'Eva', 'Tomas', 'Grace', 'Omar'];
const LAST_NAMES = ['Imran', 'Okafor', 'Lindqvist', 'Rao', 'Moreau', 'Haddad', 'Novak', 'Silva', 'Chen', 'Weber'];
const SEGMENTS = ['enterprise', 'mid-market', 'smb', 'public-sector'];
const COUNTRIES = ['GB', 'DE', 'FR', 'AE', 'SG', 'US', 'NL', 'SE'];
const CUSTOMER_STATUSES = ['active', 'active', 'active', 'suspended', 'churned'];
const METHODS = ['card', 'sepa_direct_debit', 'bank_transfer', 'wallet'];
const CURRENCIES = ['GBP', 'EUR', 'USD', 'AED'];

const INCIDENT_TEMPLATES = [
  {
    title: 'Payment authorisation timeouts',
    category: 'availability',
    service: 'payments-api',
    rootCause: 'Connection pool exhaustion in the payment authorisation service under peak load.',
    failure: 'gateway_timeout',
  },
  {
    title: 'Authentication failures for federated logins',
    category: 'authentication',
    service: 'auth-service',
    rootCause: 'Expired signing certificate on the identity provider federation endpoint.',
    failure: 'authentication_failed',
  },
  {
    title: 'Ledger replication lag',
    category: 'data-integrity',
    service: 'ledger-db',
    rootCause: 'Long-running vacuum blocked replication, delaying settlement writes.',
    failure: 'settlement_delayed',
  },
  {
    title: 'Checkout page 5xx spike',
    category: 'availability',
    service: 'checkout-web',
    rootCause: 'Bad rollout of the checkout bundle raised unhandled exceptions on submit.',
    failure: 'internal_error',
  },
  {
    title: 'Card issuer declines misclassified',
    category: 'payments',
    service: 'payments-api',
    rootCause: 'Issuer response mapping treated soft declines as hard declines.',
    failure: 'issuer_declined',
  },
  {
    title: 'Notification backlog',
    category: 'degradation',
    service: 'notification-service',
    rootCause: 'Queue consumer scaled to zero after a faulty autoscaling policy update.',
    failure: null,
  },
  {
    title: 'Fraud screening false positives',
    category: 'risk',
    service: 'payments-api',
    rootCause: 'Risk model threshold deployed without the calibration step.',
    failure: 'fraud_review_hold',
  },
  {
    title: 'Session store failover',
    category: 'availability',
    service: 'auth-service',
    rootCause: 'Primary session cache node lost quorum during a maintenance window.',
    failure: 'authentication_failed',
  },
];

const SEVERITIES = ['sev1', 'sev2', 'sev2', 'sev3'];
const APPROVERS = ['r.mcallister', 'j.fernandes', 'l.ashford', 'k.osei'];

const DAY_MS = 24 * 60 * 60 * 1000;
const BASE_TIME = Date.UTC(2026, 0, 6, 9, 0, 0);

const iso = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');

function buildCustomers() {
  return Array.from({ length: CUSTOMER_COUNT }, (_, index) => {
    const first = FIRST_NAMES[index % FIRST_NAMES.length];
    const last = LAST_NAMES[(index * 3) % LAST_NAMES.length];
    return {
      customer_id: `C${82000 + index * 37}`,
      name: `${first} ${last}`,
      email: `${first}.${last}`.toLowerCase() + `@example-${pick(['corp', 'group', 'holdings'])}.com`,
      segment: pick(SEGMENTS),
      country: pick(COUNTRIES),
      risk_score: Number(between(0.02, 0.95).toFixed(2)),
      created_at: iso(BASE_TIME - Math.floor(between(30, 900)) * DAY_MS),
      status: pick(CUSTOMER_STATUSES),
    };
  });
}

function buildIncidents() {
  return Array.from({ length: INCIDENT_COUNT }, (_, index) => {
    const template = INCIDENT_TEMPLATES[index % INCIDENT_TEMPLATES.length];
    const openedAt = BASE_TIME + index * 3 * DAY_MS + Math.floor(between(0, 6)) * 3600_000;
    const isResolved = index % 3 !== 0;
    const approved = isResolved && index % 2 === 0;
    return {
      incident_id: `INC${1800 + index * 13}`,
      title: template.title,
      severity: pick(SEVERITIES),
      status: isResolved ? 'resolved' : pick(['open', 'investigating', 'monitoring']),
      category: template.category,
      root_cause: template.rootCause,
      service: template.service,
      opened_at: iso(openedAt),
      resolved_at: isResolved ? iso(openedAt + Math.floor(between(2, 40)) * 3600_000) : null,
      approved: approved ? 1 : 0,
      approved_by: approved ? pick(APPROVERS) : null,
      failure: template.failure,
    };
  });
}

function buildTransactions(customers, incidents) {
  const failingIncidents = incidents.filter((incident) => incident.failure !== null);
  return Array.from({ length: TRANSACTION_COUNT }, (_, index) => {
    const customer = customers[index % customers.length];
    const createdAt = BASE_TIME + index * 9 * 3600_000;
    const failed = index % 3 === 0;
    const incident = failed ? failingIncidents[index % failingIncidents.length] : null;
    const status = failed ? 'failed' : pick(['settled', 'settled', 'pending', 'refunded']);
    return {
      transaction_id: `TX${82000 + index * 17}`,
      customer_id: customer.customer_id,
      amount: Number(between(12, 24000).toFixed(2)),
      currency: pick(CURRENCIES),
      status,
      method: pick(METHODS),
      failure_reason: failed ? incident.failure : null,
      created_at: iso(createdAt),
      updated_at: iso(createdAt + Math.floor(between(1, 72)) * 60_000),
      incident_id: incident ? incident.incident_id : null,
    };
  });
}

function buildAssets() {
  const kinds = ['service', 'database', 'queue', 'gateway', 'job'];
  const environments = ['production', 'production', 'staging'];
  const owners = ['platform-payments', 'identity-team', 'core-banking', 'web-platform', 'sre'];
  return Array.from({ length: ASSET_COUNT }, (_, index) => {
    const service = SERVICES[index % SERVICES.length];
    return {
      asset_id: `AST${String(140 + index * 7).padStart(4, '0')}`,
      name: `${service}-${pick(['primary', 'replica', 'edge', 'worker'])}-${index + 1}`,
      kind: kinds[index % kinds.length],
      owner: owners[index % owners.length],
      environment: environments[index % environments.length],
      service,
      status: pick(['healthy', 'healthy', 'degraded', 'maintenance']),
      created_at: iso(BASE_TIME - Math.floor(between(60, 1200)) * DAY_MS),
    };
  });
}

function insertAll(db, table, columns, rows) {
  const placeholders = columns.map(() => '?').join(', ');
  const statement = db.prepare(
    `INSERT INTO ${table} (${columns.join(', ')}) VALUES (${placeholders})`,
  );
  const insertMany = db.transaction((records) => {
    for (const record of records) {
      statement.run(columns.map((column) => record[column] ?? null));
    }
  });
  insertMany(rows);
}

function main() {
  const target = process.env.ENTERPRISE_SQLITE_PATH
    ? path.resolve(process.cwd(), process.env.ENTERPRISE_SQLITE_PATH)
    : DEFAULT_DB_PATH;

  if (fs.existsSync(target)) {
    console.log(`[seed-dev-db] ${target} already exists - leaving it untouched.`);
    console.log('[seed-dev-db] Delete it manually if you really want a fresh fixture.');
    return;
  }

  fs.mkdirSync(path.dirname(target), { recursive: true });
  const db = new Database(target);
  try {
    db.pragma('journal_mode = DELETE');
    db.exec(SCHEMA);

    const customers = buildCustomers();
    const incidents = buildIncidents();
    const transactions = buildTransactions(customers, incidents);
    const assets = buildAssets();

    insertAll(db, 'customers', Object.keys(customers[0]), customers);
    insertAll(
      db,
      'incidents',
      Object.keys(incidents[0]).filter((column) => column !== 'failure'),
      incidents,
    );
    insertAll(db, 'transactions', Object.keys(transactions[0]), transactions);
    insertAll(db, 'assets', Object.keys(assets[0]), assets);

    console.log(`[seed-dev-db] created ${target}`);
    console.log(
      `[seed-dev-db] customers=${customers.length} transactions=${transactions.length} ` +
        `incidents=${incidents.length} assets=${assets.length}`,
    );
  } finally {
    db.close();
  }
}

main();
