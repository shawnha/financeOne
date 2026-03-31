-- FinanceOne v2 — DB Schema (Supabase PostgreSQL)
-- 21개 테이블 (14 + slack + journal + intercompany_pairs + consolidation_adjustments + card_settings)
-- Schema: financeone (hanahone-erp Supabase project)

CREATE SCHEMA IF NOT EXISTS financeone;
SET search_path TO financeone;

BEGIN;

-- 1. entities — 법인
CREATE TABLE IF NOT EXISTS entities (
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
CREATE TABLE IF NOT EXISTS members (
  id            SERIAL PRIMARY KEY,
  entity_id     INTEGER NOT NULL REFERENCES entities(id),
  name          TEXT NOT NULL,
  role          TEXT DEFAULT 'staff',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  card_numbers  TEXT[] DEFAULT ARRAY[]::TEXT[],
  slack_user_id TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_members_slack ON members (entity_id, slack_user_id) WHERE slack_user_id IS NOT NULL;

-- 3. standard_accounts — K-GAAP 표준계정
CREATE TABLE IF NOT EXISTS standard_accounts (
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
CREATE TABLE IF NOT EXISTS internal_accounts (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  code                TEXT NOT NULL,
  name                TEXT NOT NULL,
  standard_account_id INTEGER REFERENCES standard_accounts(id),
  parent_id           INTEGER REFERENCES internal_accounts(id),
  sort_order          INTEGER NOT NULL DEFAULT 0,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  is_recurring        BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(entity_id, code)
);

-- 5. uploaded_files — 업로드 파일 추적
CREATE TABLE IF NOT EXISTS uploaded_files (
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
CREATE TABLE IF NOT EXISTS transactions (
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

  -- 파서에서 추출한 원본 데이터 (재매칭용)
  parsed_member_name     TEXT,
  card_number            TEXT,

  -- 취소 건
  is_cancel              BOOLEAN NOT NULL DEFAULT FALSE,

  -- 중복 제거
  is_duplicate           BOOLEAN NOT NULL DEFAULT FALSE,
  duplicate_of_id        INTEGER REFERENCES transactions(id),

  note                   TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tx_entity_date ON transactions(entity_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_standard ON transactions(standard_account_id);
CREATE INDEX IF NOT EXISTS idx_tx_confirmed ON transactions(is_confirmed);
CREATE INDEX IF NOT EXISTS idx_tx_file_id ON transactions(file_id);

-- 7. balance_snapshots — 잔고 스냅샷
CREATE TABLE IF NOT EXISTS balance_snapshots (
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
CREATE TABLE IF NOT EXISTS forecasts (
  id               SERIAL PRIMARY KEY,
  entity_id        INTEGER NOT NULL REFERENCES entities(id),
  year             INTEGER NOT NULL,
  month            INTEGER NOT NULL,
  category         TEXT NOT NULL,
  subcategory      TEXT,
  type             TEXT NOT NULL,
  forecast_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
  actual_amount    NUMERIC(18,2),
  is_recurring        BOOLEAN NOT NULL DEFAULT FALSE,
  internal_account_id INTEGER REFERENCES internal_accounts(id),
  note                TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_account
  ON forecasts (entity_id, year, month, internal_account_id, type)
  WHERE internal_account_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_category
  ON forecasts (entity_id, year, month, category, subcategory, type)
  WHERE internal_account_id IS NULL;

-- 9. exchange_rates — 환율
CREATE TABLE IF NOT EXISTS exchange_rates (
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
CREATE TABLE IF NOT EXISTS financial_statements (
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
  base_currency             TEXT DEFAULT 'KRW',
  status                    TEXT NOT NULL DEFAULT 'draft',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, fiscal_year, ki_num, start_month, end_month)
);

-- 11. financial_statement_line_items — 재무제표 항목
CREATE TABLE IF NOT EXISTS financial_statement_line_items (
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
CREATE TABLE IF NOT EXISTS settings (
  id         SERIAL PRIMARY KEY,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  entity_id  INTEGER REFERENCES entities(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (key, entity_id)
);

-- entity_id NULL인 경우 중복 방지 (전역 설정)
CREATE UNIQUE INDEX IF NOT EXISTS idx_settings_global ON settings(key) WHERE entity_id IS NULL;

-- 13. mapping_rules — AI 매핑 학습
CREATE TABLE IF NOT EXISTS mapping_rules (
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

CREATE INDEX IF NOT EXISTS idx_mapping_pattern ON mapping_rules(counterparty_pattern);

-- 14. gaap_mapping — US GAAP ↔ K-GAAP 매핑
CREATE TABLE IF NOT EXISTS gaap_mapping (
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

-- 15. slack_messages — Slack 경비 메시지
CREATE TABLE IF NOT EXISTS slack_messages (
  id                        SERIAL PRIMARY KEY,
  entity_id                 INTEGER REFERENCES entities(id),
  ts                        TEXT NOT NULL UNIQUE,
  channel                   TEXT NOT NULL,
  user_id                   TEXT,
  text                      TEXT,
  parsed_amount             NUMERIC(18,2),
  parsed_amount_vat_included NUMERIC(18,2),
  vat_flag                  TEXT,
  project_tag               TEXT,
  is_completed              BOOLEAN NOT NULL DEFAULT FALSE,
  raw_json                  TEXT,
  date_override             DATE,
  is_cancelled              BOOLEAN NOT NULL DEFAULT FALSE,
  deposit_completed_date    DATE,
  reply_count               INTEGER NOT NULL DEFAULT 0,
  thread_replies_json       TEXT,
  member_id                 INTEGER REFERENCES members(id),
  message_type              TEXT,
  slack_status              TEXT DEFAULT 'pending',
  currency                  TEXT DEFAULT 'KRW',
  withholding_tax           BOOLEAN DEFAULT FALSE,
  sender_name               TEXT,
  sub_amounts               JSONB,
  parsed_structured           JSONB,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_slack_ts ON slack_messages(ts);
CREATE INDEX IF NOT EXISTS idx_slack_entity ON slack_messages(entity_id);

-- 16. transaction_slack_match — 거래 ↔ Slack 매칭
CREATE TABLE IF NOT EXISTS transaction_slack_match (
  id                   SERIAL PRIMARY KEY,
  transaction_id       INTEGER NOT NULL REFERENCES transactions(id),
  slack_message_id     INTEGER NOT NULL REFERENCES slack_messages(id),
  match_confidence     NUMERIC(3,2),
  is_manual            BOOLEAN NOT NULL DEFAULT FALSE,
  is_confirmed         BOOLEAN NOT NULL DEFAULT FALSE,
  ai_reasoning         TEXT,
  note                 TEXT,
  amount_override      NUMERIC(18,2),
  text_override        TEXT,
  project_tag_override TEXT,
  item_index           INTEGER DEFAULT NULL,
  item_description     TEXT DEFAULT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_tx ON transaction_slack_match(transaction_id);
CREATE INDEX IF NOT EXISTS idx_match_slack ON transaction_slack_match(slack_message_id);

-- 17. journal_entries — 분개 헤더
CREATE TABLE IF NOT EXISTS journal_entries (
  id             SERIAL PRIMARY KEY,
  entity_id      INTEGER NOT NULL REFERENCES entities(id),
  transaction_id INTEGER REFERENCES transactions(id),
  entry_date     DATE NOT NULL,
  description    TEXT,
  is_adjusting   BOOLEAN NOT NULL DEFAULT FALSE,
  is_closing     BOOLEAN NOT NULL DEFAULT FALSE,
  status         TEXT NOT NULL DEFAULT 'posted',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_je_entity_date ON journal_entries(entity_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_je_transaction ON journal_entries(transaction_id);

-- 18. journal_entry_lines — 분개 라인 (차변/대변)
CREATE TABLE IF NOT EXISTS journal_entry_lines (
  id                  SERIAL PRIMARY KEY,
  journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  standard_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  debit_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,
  credit_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
  description         TEXT,
  sort_order          INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT chk_debit_or_credit CHECK (
    (debit_amount > 0 AND credit_amount = 0) OR
    (debit_amount = 0 AND credit_amount > 0)
  )
);

CREATE INDEX IF NOT EXISTS idx_jel_entry ON journal_entry_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_jel_account ON journal_entry_lines(standard_account_id);

-- 19. intercompany_pairs — 내부거래 매칭
CREATE TABLE IF NOT EXISTS intercompany_pairs (
  id               SERIAL PRIMARY KEY,
  entity_a_id      INTEGER NOT NULL REFERENCES entities(id),
  entity_b_id      INTEGER NOT NULL REFERENCES entities(id),
  transaction_a_id INTEGER REFERENCES transactions(id),
  transaction_b_id INTEGER REFERENCES transactions(id),
  amount           NUMERIC(18,2) NOT NULL,
  currency         TEXT NOT NULL,
  match_date       DATE NOT NULL,
  match_method     TEXT NOT NULL DEFAULT 'auto',
  is_confirmed     BOOLEAN NOT NULL DEFAULT FALSE,
  description      TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 20. consolidation_adjustments — 연결 조정 감사 추적
CREATE TABLE IF NOT EXISTS consolidation_adjustments (
  id               SERIAL PRIMARY KEY,
  statement_id     INTEGER NOT NULL REFERENCES financial_statements(id) ON DELETE CASCADE,
  adjustment_type  TEXT NOT NULL,
  account_code     TEXT NOT NULL,
  description      TEXT,
  original_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
  adjusted_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
  source_entity_id INTEGER REFERENCES entities(id),
  exchange_rate    NUMERIC(12,4),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exchange_rates_lookup ON exchange_rates(from_currency, to_currency, date DESC);

-- 21. card_settings — 카드 설정 (결제일, 카드사 정보)
CREATE TABLE IF NOT EXISTS card_settings (
  id           SERIAL PRIMARY KEY,
  entity_id    INTEGER NOT NULL REFERENCES entities(id),
  card_name    TEXT NOT NULL,
  source_type  TEXT NOT NULL,
  payment_day  INTEGER NOT NULL DEFAULT 15,
  card_number  TEXT,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, source_type, card_number)
);

COMMIT;
