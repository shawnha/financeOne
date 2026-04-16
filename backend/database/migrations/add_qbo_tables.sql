-- QBO Integration: 2 new tables + mapping_rules source column
-- Run: psql $DATABASE_URL -f backend/database/migrations/add_qbo_tables.sql

SET search_path TO financeone;

-- mapping_rules: source column for provenance tracking
ALTER TABLE mapping_rules ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';

-- 22. qbo_accounts — QuickBooks Chart of Accounts
CREATE TABLE IF NOT EXISTS qbo_accounts (
  id               SERIAL PRIMARY KEY,
  entity_id        INTEGER NOT NULL REFERENCES entities(id),
  qbo_id           TEXT NOT NULL,
  name             TEXT NOT NULL,
  account_type     TEXT,
  account_sub_type TEXT,
  full_name        TEXT,
  synced_at        TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(entity_id, qbo_id)
);

-- 23. qbo_transaction_lines — QBO 라인 레벨 거래
CREATE TABLE IF NOT EXISTS qbo_transaction_lines (
  id              SERIAL PRIMARY KEY,
  entity_id       INTEGER NOT NULL REFERENCES entities(id),
  qbo_txn_id      TEXT NOT NULL,
  txn_type        TEXT,
  txn_date        DATE,
  payee           TEXT,
  account_name    TEXT,
  qbo_account_id  TEXT,
  line_number     INTEGER DEFAULT 1,
  memo            TEXT,
  amount          NUMERIC(15,2),
  synced_at       TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(entity_id, qbo_txn_id, qbo_account_id, line_number)
);
