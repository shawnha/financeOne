# Transactions Page Design

## Layout
- 상단: 법인 선택 + 기간 필터 + 검색
- 메인: Dense Table (전체 너비)
- 하단: 페이지네이션

## Table Columns
| Column | Width | Align | Notes |
|--------|-------|-------|-------|
| 날짜 | 100px | left | YYYY-MM-DD |
| 설명 | flex | left | 거래처 + 설명 |
| 수입 | 120px | right | tabular-nums, green |
| 지출 | 120px | right | tabular-nums, red |
| 계정과목 | 140px | left | 매핑된 계정 |
| 신뢰도 | 80px | center | AI 매핑: 0-100% badge |
| 상태 | 80px | center | 확정/미확정 badge |
| 액션 | 60px | center | 편집/확정 버튼 |

## Filters
- 법인, 기간(월/분기/커스텀), 상태, 매핑소스, 검색어

## Bulk Actions
- 선택한 거래 일괄 확정
- 선택한 거래 일괄 계정과목 변경
