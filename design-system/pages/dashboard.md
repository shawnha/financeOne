# Dashboard Page Design

## Layout
- Bento Grid: 3-column (lg), 2-column (md), 1-column (sm)
- 상단: 법인 선택 탭 (HOI | 한아원코리아 | 한아원리테일 | 연결)
- KPI 카드 행: 총잔고, 이번달 수입, 이번달 지출, 현금 런웨이

## KPI Cards (1×1)
- 금액: 28px bold, tabular-nums
- 증감: 12px, 화살표 + 퍼센트 (green/red)
- 레이블: 12px muted-foreground

## Cash Flow Chart (2×1)
- Recharts BarChart
- 수입(green) vs 지출(red), 6개월
- Tooltip: 월, 수입, 지출, 순현금흐름

## Recent Transactions (2×1)
- 최근 10건
- 컬럼: 날짜, 설명, 금액, 매핑 상태
- 미확정 거래: yellow badge

## Quick Actions (1×1)
- 업로드, 거래 확인, 재무제표
