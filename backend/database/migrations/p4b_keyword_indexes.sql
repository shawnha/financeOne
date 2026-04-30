-- P4-B: keyword cascade SQL 성능 최적화
--
-- Code Reviewer P1-3: ILIKE substring 검색은 일반 인덱스 못 씀.
-- pg_trgm GIN 인덱스로 substring 매칭 가속.
--
-- 거래량 증가 시 (Phase 3+) 효과 큼. 현재 데이터셋(< 5K transactions, < 200 keywords)
-- 에서는 미세한 차이지만, 향후 회귀 방지를 위해 미리 추가.

-- pg_trgm extension 활성화 (이미 있으면 skip)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- keyword_mapping_rules.keyword GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_keyword_mapping_rules_keyword_trgm
ON financeone.keyword_mapping_rules
USING gin (keyword financeone.gin_trgm_ops);

-- standard_account_keywords.keyword GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_standard_account_keywords_keyword_trgm
ON financeone.standard_account_keywords
USING gin (keyword financeone.gin_trgm_ops);

-- entity_id 단순 인덱스 (keyword_mapping_rules)
CREATE INDEX IF NOT EXISTS idx_keyword_mapping_rules_entity
ON financeone.keyword_mapping_rules (entity_id);

-- internal_accounts.entity_id + standard_account_id 복합 인덱스
-- (D2 internal_account 추론 sub-query 가속)
CREATE INDEX IF NOT EXISTS idx_internal_accounts_entity_std
ON financeone.internal_accounts (entity_id, standard_account_id, is_active);
