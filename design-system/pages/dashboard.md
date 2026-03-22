# Dashboard Page Design

## Layout
- Bento Grid: 3-column (lg), 2-column (md), 1-column (sm)
- 상단: 법인 선택 탭 (HOI | 한아원코리아 | 한아원리테일 | 연결[disabled, Phase 3])
- KPI 카드 행: 총잔고, 이번달 수입, 이번달 지출, 현금 런웨이

## Entity Tab (전체 화면 공통)
- URL: `?entity=HOK` 쿼리 파라미터로 관리
- 전역 상태: 페이지 이동 시 선택된 법인 유지
- '연결' 탭: Phase 3까지 disabled (회색 + "Phase 3" 툴팁)
- 3개 법인 전 화면 통일 표시 (Dashboard, Transactions, Upload, Slack Match)

## KPI Cards (1x1, 4개)
- 금액: 28px IBM Plex Mono bold, tabular-nums (`--color-text`)
- 증감: 12px, 화살표 + 퍼센트 (`--profit-color` / `--loss-color`)
- 레이블: 12px IBM Plex Sans, `--neutral-color`
- 카드 배경: `--color-secondary` (#1E293B), radius 12px, padding 24px

## Cash Flow Chart (2x1)
- Recharts BarChart (요약 — 최근 6개월)
- 수입: `--chart-profit` (#22C55E) / 지출: `--chart-loss` (#EF4444)
- Tooltip: 월, 수입, 지출, 순현금흐름 (formatted)
- 차트 하단 "상세 보기" 링크 → `/cashflow` 페이지로 이동
- Grid: dashed, `#334155`

## Recent Transactions (2x1)
- 최근 10건
- 컬럼: 날짜, 설명, 금액, 매핑 상태
- 미확정 거래: `--warning-color` badge
- 하단 "전체 보기" 링크 → `/transactions`

## Quick Actions (1x1) — 동적 CTA
- "미확정 거래 N건 확인" → `/transactions?filter=unconfirmed` (N > 0일 때 `--warning-color`)
- "Excel 업로드" → `/upload` (Lucide `Upload` 아이콘)
- "현금흐름 상세" → `/cashflow` (Lucide `TrendingUp` 아이콘)
- 각 버튼: `btn-secondary` 스타일, 44px 최소 높이

## Interaction States

| State | Implementation |
|-------|----------------|
| LOADING | KPI 카드 4개 스켈레톤 (pulse) + 차트 영역 스켈레톤 + 거래 리스트 스켈레톤 (5행) |
| EMPTY | KPI ₩0 표시 + 차트 영역에 "첫 거래 데이터를 업로드해보세요" 메시지 + 업로드 CTA 버튼 (초록 `--color-cta`). 최근 거래에도 "업로드 후 여기에 표시됩니다" 안내 |
| ERROR | "데이터를 불러올 수 없습니다. 서버 연결을 확인하세요." + 재시도 버튼 |
| SUCCESS | 정상 데이터 표시 |
| PARTIAL | 경고 배너 (`--warning-color`) "일부 법인 데이터만 표시됩니다" + 가용 데이터 표시 |

## Post-Upload Banner
업로드 직후 거래내역으로 이동 시 상단에 요약 배너 표시:
- "새로 업로드된 461건 중 387건 AI 매핑 완료, 74건 수동 확인 필요"
- 배너 배경: `--ai-accent` (#6366F1) / 10% opacity
- "미확정만 보기" 필터 바로가기 버튼
- 닫기(X) 버튼으로 dismiss

## Responsive
- **lg (1024px+)**: 4col KPI + 2col 차트 + 1col 거래 + 1col Quick Actions
- **md (768px)**: 2col KPI + 차트 전체폭 + 거래 전체폭 + Quick Actions 전체폭
- **sm (375px)**: 1col 모두 stacked. 차트 높이 200px로 축소
