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
| 1 | ☑ | - | 40px | center | 일괄 선택 체크박스 |
| 2 | 날짜 | `date` | 100px | left | YYYY-MM-DD, 정렬 가능 |
| 3 | 출처 | `source_type` | 90px | left | 아이콘+라벨 (롯데카드/우리카드/우리은행) |
| 4 | 회원 | `member_id` → JOIN members | 80px | left | 카드 사용자 (은행 거래는 빈값) |
| 5 | 내역 | `description` | flex | left | 거래 설명 |
| 6 | 거래처 | `counterparty` | 140px | left | 가맹점/상대방, 정렬 가능 |
| 7 | 수입 | `amount` (type='in') | 120px | right | green, tabular-nums, Geist Mono |
| 8 | 지출 | `amount` (type='out') | 120px | right | red, tabular-nums, Geist Mono |
| 9 | 내부 계정 | `internal_account_id` → JOIN | 120px | left | 클릭하여 변경 가능 |
| 10 | 표준 계정 | `standard_account_id` → JOIN | 120px | left | 클릭하여 변경 가능 |
| 11 | 신뢰 | `mapping_confidence` | 60px | center | 0-100% badge (color by level) |

- 확정 여부: `is_confirmed` — 별도 컬럼 없이 체크박스 일괄 확정 + 행 클릭 편집
- 중복 거래: `is_duplicate=true` 행은 회색 처리 + 금액 취소선 (접힘 아님)

## Filters
- 검색: 내역, 거래처, 메모 통합 검색
- 기간: 날짜 range picker + 월 선택 드롭다운
- 회원: 드롭다운 필터 (카드 사용자별)
- 표준 계정: 드롭다운 필터
- 내부 계정: 드롭다운 필터
- 미분류만: 체크박스 (is_confirmed=false AND standard_account_id IS NULL)
- 출처: 롯데카드/우리카드/우리은행 토글

## Bulk Actions (체크박스 선택 후)
- 선택한 거래 일괄 확정 → toast "✓ N건 확정 완료"
- 선택한 거래 일괄 계정과목 변경

## Row Interaction
- 행 클릭 → 상세/편집 모달 (계정과목 변경, 메모 추가)
- 내부 계정/표준 계정 셀 클릭 → 인라인 드롭다운 변경

## Source Type Icons
- `lotte_card` → 롯데카드 아이콘 (빨간색 계열)
- `woori_card` → 우리카드 아이콘 (파란색 계열)
- `woori_bank` → 우리은행 아이콘 (파란색 계열)
- `manual` → 수동 입력 아이콘 (회색)

## Interaction States

| State | Implementation |
|-------|----------------|
| LOADING | 테이블 형태 스켈레톤 (11컬럼 x 10행, pulse 1.5s). 헤더는 실제 컬럼명 표시 |
| EMPTY | 테이블 영역에 "거래 데이터가 없습니다. Excel 파일을 업로드해보세요." + 업로드 바로가기 버튼 (`btn-primary`) |
| ERROR | "데이터를 불러올 수 없습니다." + 재시도 버튼. DB 연결 실패 시 exponential backoff 메시지 |
| SUCCESS | 정상 테이블 표시 |
| PARTIAL | 경고 배너 (`--warning-color`) "일부 데이터만 표시됩니다" + 가용 데이터 표시 |

## Post-Upload Summary Banner
업로드 직후 이동 시 상단 배너:
- "새로 업로드된 N건 중 M건 AI 매핑 완료, K건 수동 확인 필요"
- `--ai-accent` (#6366F1) 배경 10% opacity
- "미확정만 보기" 필터 바로가기 + 닫기(X) 버튼

## Responsive
- **lg (1024px+)**: 전체 11컬럼 표시, overflow-x-auto
- **md (768px)**: 날짜, 내역, 수입, 지출, 신뢰 5컬럼만 표시. 나머지는 행 클릭 시 상세 모달
- **sm (375px)**: 날짜, 내역, 금액(수입/지출 합침) 3컬럼 + 가로 스크롤. 체크박스/벌크 액션 비활성화
