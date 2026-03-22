-- FinanceOne v2 — DB Schema (Neon PostgreSQL)
-- 14개 테이블, 모든 테이블에 entity_id 포함 원칙
-- PRD SQLite 문법 → PostgreSQL 변환

BEGIN;

-- 1. entities — 법인
CREATE TABLE entities (
  id          SERIAL PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  type        TEXT NOT NULL,
  currency    TEXT NOT NULL DEFAULT 'KRW',
  parent_id   INTEGER REFERENCES entities(id),
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. members — 팀 멤버
CREATE TABLE members (
  id          SERIAL PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES entities(id),
  name        TEXT NOT NULL,
  role        TEXT DEFAULT 'staff',
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. standard_accounts — K-GAAP 표준계정
CREATE TABLE standard_accounts (
  id           SERIAL PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  category     TEXT NOT NULL,
  subcategory  TEXT,
  normal_side  TEXT NOT NULL,
  parent_code  TEXT REFERENCES standard_accounts(code),
  sort_order   INTEGER NOT NULL DEFAULT 0,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

-- 4. internal_accounts — 내부 계정과목
CREATE TABLE internal_accounts (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  code                TEXT NOT NULL,
  name                TEXT NOT NULL,
  standard_account_id INTEGER REFERENCES standard_accounts(id),
  parent_id           INTEGER REFERENCES internal_accounts(id),
  sort_order          INTEGER NOT NULL DEFAULT 0,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(entity_id, code)
);

-- 5. uploaded_files — 업로드 파일 추적
CREATE TABLE uploaded_files (
  id           SERIAL PRIMARY KEY,
  entity_id    INTEGER NOT NULL REFERENCES entities(id),
  filename     TEXT NOT NULL,
  source_type  TEXT NOT NULL,
  file_path    TEXT NOT NULL,
  row_count    INTEGER,
  status       TEXT NOT NULL DEFAULT 'pending',
  uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  uploaded_by  INTEGER REFERENCES members(id)
);

-- 6. transactions — 거래내역 (핵심)
CREATE TABLE transactions (
  id                     SERIAL PRIMARY KEY,
  entity_id              INTEGER NOT NULL REFERENCES entities(id),
  file_id                INTEGER REFERENCES uploaded_files(id),

  -- 기본 정보
  date                   DATE NOT NULL,
  amount                 NUMERIC(18,2) NOT NULL,
  currency               TEXT NOT NULL DEFAULT 'KRW',
  type                   TEXT NOT NULL,
  description            TEXT NOT NULL,
  counterparty           TEXT,
  member_id              INTEGER REFERENCES members(id),
  source_type            TEXT NOT NULL,

  -- 계정과목 매핑
  internal_account_id    INTEGER REFERENCES internal_accounts(id),
  standard_account_id    INTEGER REFERENCES standard_accounts(id),
  mapping_confidence     NUMERIC(3,2),
  mapping_source         TEXT,
  is_confirmed           BOOLEAN NOT NULL DEFAULT FALSE,

  -- 법인 간 거래
  is_intercompany        BOOLEAN NOT NULL DEFAULT FALSE,
  counterparty_entity_id INTEGER REFERENCES entities(id),
  intercompany_pair_id   INTEGER,

  -- 중복 제거
  is_duplicate           BOOLEAN NOT NULL DEFAULT FALSE,
  duplicate_of_id        INTEGER REFERENCES transactions(id),

  note                   TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tx_entity_date ON transactions(entity_id, date);
CREATE INDEX idx_tx_standard ON transactions(standard_account_id);
CREATE INDEX idx_tx_confirmed ON transactions(is_confirmed);

-- 7. balance_snapshots — 잔고 스냅샷
CREATE TABLE balance_snapshots (
  id            SERIAL PRIMARY KEY,
  entity_id     INTEGER NOT NULL REFERENCES entities(id),
  date          DATE NOT NULL,
  account_name  TEXT NOT NULL,
  account_type  TEXT NOT NULL,
  balance       NUMERIC(18,2) NOT NULL,
  currency      TEXT NOT NULL DEFAULT 'KRW',
  source        TEXT NOT NULL DEFAULT 'manual',
  note          TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, date, account_name)
);

-- 8. forecasts — 예측 수입/지출
CREATE TABLE forecasts (
  id               SERIAL PRIMARY KEY,
  entity_id        INTEGER NOT NULL REFERENCES entities(id),
  year             INTEGER NOT NULL,
  month            INTEGER NOT NULL,
  category         TEXT NOT NULL,
  subcategory      TEXT,
  type             TEXT NOT NULL,
  forecast_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
  actual_amount    NUMERIC(18,2),
  is_recurring     BOOLEAN NOT NULL DEFAULT FALSE,
  note             TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, year, month, category, subcategory, type)
);

-- 9. exchange_rates — 환율
CREATE TABLE exchange_rates (
  id            SERIAL PRIMARY KEY,
  date          DATE NOT NULL,
  from_currency TEXT NOT NULL,
  to_currency   TEXT NOT NULL,
  rate          NUMERIC(12,4) NOT NULL,
  source        TEXT NOT NULL DEFAULT 'manual',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(date, from_currency, to_currency)
);

-- 10. financial_statements — 재무제표 헤더
CREATE TABLE financial_statements (
  id                        SERIAL PRIMARY KEY,
  entity_id                 INTEGER NOT NULL REFERENCES entities(id),
  fiscal_year               INTEGER NOT NULL,
  ki_num                    INTEGER NOT NULL DEFAULT 3,
  start_month               INTEGER NOT NULL DEFAULT 1,
  end_month                 INTEGER NOT NULL DEFAULT 12,
  is_consolidated           BOOLEAN NOT NULL DEFAULT FALSE,
  company_name              TEXT,
  representative_name       TEXT,
  business_registration_no  TEXT,
  corporate_registration_no TEXT,
  company_address           TEXT,
  business_type             TEXT,
  business_item             TEXT,
  auditor_name              TEXT,
  notes                     TEXT,
  status                    TEXT NOT NULL DEFAULT 'draft',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, fiscal_year, ki_num, start_month, end_month)
);

-- 11. financial_statement_line_items — 재무제표 항목
CREATE TABLE financial_statement_line_items (
  id                SERIAL PRIMARY KEY,
  statement_id      INTEGER NOT NULL REFERENCES financial_statements(id) ON DELETE CASCADE,
  statement_type    TEXT NOT NULL,
  account_code      TEXT,
  line_key          TEXT NOT NULL,
  label             TEXT NOT NULL,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  is_section_header BOOLEAN NOT NULL DEFAULT FALSE,
  auto_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
  auto_debit        NUMERIC(18,2) NOT NULL DEFAULT 0,
  auto_credit       NUMERIC(18,2) NOT NULL DEFAULT 0,
  manual_amount     NUMERIC(18,2),
  manual_debit      NUMERIC(18,2),
  manual_credit     NUMERIC(18,2),
  note              TEXT,
  UNIQUE(statement_id, statement_type, line_key)
);

-- 12. settings — 앱 설정
CREATE TABLE settings (
  id         SERIAL PRIMARY KEY,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  entity_id  INTEGER REFERENCES entities(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (key, entity_id)
);

-- entity_id NULL인 경우 중복 방지 (전역 설정)
CREATE UNIQUE INDEX idx_settings_global ON settings(key) WHERE entity_id IS NULL;

-- 13. mapping_rules — AI 매핑 학습
CREATE TABLE mapping_rules (
  id                   SERIAL PRIMARY KEY,
  entity_id            INTEGER REFERENCES entities(id),
  counterparty_pattern TEXT NOT NULL,
  standard_account_id  INTEGER NOT NULL REFERENCES standard_accounts(id),
  internal_account_id  INTEGER REFERENCES internal_accounts(id),
  confidence           NUMERIC(3,2) NOT NULL DEFAULT 1.0,
  hit_count            INTEGER NOT NULL DEFAULT 0,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mapping_pattern ON mapping_rules(counterparty_pattern);

-- 14. gaap_mapping — US GAAP ↔ K-GAAP 매핑
CREATE TABLE gaap_mapping (
  id                    SERIAL PRIMARY KEY,
  us_gaap_code          TEXT NOT NULL UNIQUE,
  us_gaap_name          TEXT NOT NULL,
  standard_account_id   INTEGER REFERENCES standard_accounts(id),
  category              TEXT NOT NULL,
  mapping_source        TEXT DEFAULT 'ai',
  is_confirmed          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
