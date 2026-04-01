-- Auto-matching v2: pg_trgm, match_type, keyword tables
-- Run against financeone schema

SET search_path TO financeone;

-- 1. pg_trgm 확장 활성화
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. mapping_rules에 match_type 컬럼 추가
ALTER TABLE mapping_rules ADD COLUMN IF NOT EXISTS match_type varchar(20) DEFAULT 'exact';
-- values: 'exact' | 'similar' | 'keyword' | 'ai'

-- 3. counterparty_pattern 유사도 인덱스 (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_mapping_rules_trgm
  ON mapping_rules USING gin (counterparty_pattern gin_trgm_ops);

-- 4. entity_id + counterparty_pattern 복합 인덱스 (기존 쿼리 최적화)
CREATE INDEX IF NOT EXISTS idx_mapping_rules_entity_pattern
  ON mapping_rules(entity_id, counterparty_pattern);

-- 5. 키워드 매핑 규칙 테이블
CREATE TABLE IF NOT EXISTS keyword_mapping_rules (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  keyword             VARCHAR(100) NOT NULL,
  match_field         VARCHAR(20) NOT NULL DEFAULT 'description',
  internal_account_id INTEGER NOT NULL REFERENCES internal_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.75,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(entity_id, keyword, match_field)
);

-- 6. 일상어 -> 표준계정 매핑 사전
CREATE TABLE IF NOT EXISTS standard_account_keywords (
  id                  SERIAL PRIMARY KEY,
  keyword             VARCHAR(100) NOT NULL UNIQUE,
  standard_account_id INTEGER NOT NULL REFERENCES standard_accounts(id),
  confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.80
);

-- 7. 일상어 사전 시드 데이터
INSERT INTO standard_account_keywords (keyword, standard_account_id, confidence)
SELECT v.keyword, sa.id, 0.85
FROM (VALUES
  ('회식', '50400'),
  ('택시', '51300'),
  ('식대', '50400'),
  ('커피', '50600'),
  ('사무용품', '51400'),
  ('인터넷', '50700'),
  ('전화', '50700'),
  ('임대', '50500'),
  ('월세', '50500'),
  ('급여', '50200'),
  ('보험', '51100'),
  ('광고', '51600'),
  ('수수료', '51500'),
  ('이자', '52000')
) AS v(keyword, std_code)
JOIN standard_accounts sa ON sa.code = v.std_code
ON CONFLICT (keyword) DO NOTHING;
