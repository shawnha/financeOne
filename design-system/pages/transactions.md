# Transactions Page Design

## Layout
- 상단: 법인 선택 탭 + 기간 필터 + 검색
- 메인: Dense Table (전체 너비)
- 하단: 페이지네이션

## Header Actions
- 건수 표시 (예: "461건")
- CSV 다운로드 버튼
- AI 매핑 (전체) 버튼
- 표준계정 재매핑 (전체) 버튼

## Table Columns

| # | Column | DB Field | Width | Align | Notes |
|---|--------|----------|-------|-------|-------|
| 1 | ☑️ | - | 40px | center | 일괄 선택 체크박스 |
| 2 | 날짜 | `date` | 100px | left | YYYY-MM-DD, 정렬 가능 |
| 3 | 출처 | `source_type` | 90px | left | 아이콘+라벨 (롯데카드/우리카드/우리은행) |
| 4 | 내역 | `description` | flex | left | 거래 설명 |
| 5 | 거래처 | `counterparty` | 140px | left | 가맹점/상대방, 정렬 가능 |
| 6 | 수입 | `amount` (type='in') | 120px | right | green, tabular-nums, IBM Plex Mono |
| 7 | 지출 | `amount` (type='out') | 120px | right | red, tabular-nums, IBM Plex Mono |
| 8 | 내부 계정 | `internal_account_id` → JOIN | 120px | left | 클릭하여 변경 가능 |
| 9 | 표준 계정 | `standard_account_id` → JOIN | 120px | left | 클릭하여 변경 가능 |
| 10 | 신뢰 | `mapping_confidence` | 60px | center | 0-100% badge (color by level) |

- 확정 여부: `is_confirmed` — 별도 컬럼 없이 체크박스 일괄 확정 + 행 클릭 편집
- 중복 거래: `is_duplicate=true` 행은 회색 처리 + 취소선 또는 접힘 처리

## Filters
- 검색: 내역, 거래처, 메모 통합 검색
- 기간: 날짜 range picker + 월 선택 드롭다운
- 표준 계정: 드롭다운 필터
- 내부 계정: 드롭다운 필터
- 미분류만: 체크박스 (is_confirmed=false AND standard_account_id IS NULL)
- 출처: 롯데카드/우리카드/우리은행 토글

## Bulk Actions (체크박스 선택 후)
- 선택한 거래 일괄 확정
- 선택한 거래 일괄 계정과목 변경

## Row Interaction
- 행 클릭 → 상세/편집 모달 (계정과목 변경, 메모 추가)
- 내부 계정/표준 계정 셀 클릭 → 인라인 드롭다운 변경

## Source Type Icons
- `lotte_card` → 롯데카드 아이콘 (빨간색 계열)
- `woori_card` → 우리카드 아이콘 (파란색 계열)
- `woori_bank` → 우리은행 아이콘 (파란색 계열)
- `manual` → 수동 입력 아이콘 (회색)
