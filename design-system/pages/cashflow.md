# Cashflow Page Design

> Design decisions from plan-design-review (2026-03-26).
> Overrides MASTER.md where specified.

## Layout

- 3-tab structure: 실제 현금흐름 | 예상 현금흐름 | 비용 (카드 사용)
- Tab bar: full-width, color-coded underline (green / amber / purple)
- 상단: EntityTabs (법인 선택) — 기존 컴포넌트 재사용
- Per-tab layout: Header (tab title + actions) → Month nav → Chart → KPI strip → Table

## Tab Bar

- Active tab: `border-b-2` with tab color (green/amber/purple)
- Inactive tab: `text-muted-foreground`, no underline
- Tab colors: 실제=`--profit-color`, 예상=`--warning-color`, 비용=`--purple` (#8B5CF6)
- No card-style tab preview — simple text tabs

## Month Navigation

- **Pattern:** Scrollable pill strip with left/right arrows
- Only months with uploaded data are shown (no empty months)
- Active month: filled pill (tab color bg + white text)
- Inactive month: ghost pill (`bg-muted/30`)
- Arrow buttons: `◀` / `▶`, disabled at data boundaries
- Layout: `flex items-center gap-2`, horizontally scrollable on overflow

```
◀ [12월] [1월●] [2월] [3월] ▶
```

## Action Buttons (per tab header)

| Tab | Actions |
|-----|---------|
| 실제 현금흐름 | [내보내기] |
| 예상 현금흐름 | [항목 추가] [내보내기] |
| 비용 (카드 사용) | [⚙️ 카드 설정] [내보내기] |

- Buttons: `variant="outline" size="sm"`, right-aligned in tab header
- 항목 추가: opens forecast input modal (see below)
- ⚙️: opens card settings slide-over (see below)

## KPI Cards (4-card strip)

### 실제 현금흐름 탭
| Card | Value | Subtext |
|------|-------|---------|
| 기초 잔고 | ₩161.0M | 전월 기말잔고 |
| 입금 | +₩53.2M | `--profit-color` |
| 출금 | -₩107.1M | `--loss-color` |
| 기말 잔고 | ₩107.2M | 순: ±₩X.XM |

### 예상 현금흐름 탭
| Card | Value | Subtext |
|------|-------|---------|
| 기초 잔고 | ₩107.2M | 전월 확정 기말잔고 |
| 예상 입금 | +₩226.7M | `--profit-color` |
| 예상 출금 | -₩180.3M | `--loss-color` |
| 예상 기말 | ₩153.6M | ±카드 시차 보정 |

### 비용 (카드 사용) 탭
| Card | Value | Subtext |
|------|-------|---------|
| 카드 사용 총액 | ₩17.7M | 당월 사용 |
| 카드 수 | 2장 | 활성 카드 |
| 선결제 | ₩5.4M | 즉시 출금분 |
| 후결제 | ₩12.3M | 다음달 결제 |

### KPI Card Styling
- Grid: `grid-cols-4 gap-3` (lg), `grid-cols-2 gap-3` (md/sm)
- Amount: Geist Mono 28px 700, `tabular-nums`
- Label: Geist 12px 400, `--neutral-color`
- Card: `bg-secondary`, `rounded-xl`, `p-4`
- Count-up animation: 600ms ease-out (on tab change / data load)

## Charts

### 실제 탭 Chart
- **Type:** Recharts ComposedChart (Bar + Line)
- 입금: green gradient bar (`#22C55E` → `rgba(34,197,94,0.1)`)
- 출금: red gradient bar (`#EF4444` → `rgba(239,68,68,0.1)`)
- 잔고 추이: Line (white, 2px)
- 비선택 월: `opacity: 0.35`
- Animation: 300ms ease-out
- Tooltip: hover, shows date + 입금 + 출금 + 순현금흐름 (formatted)
- Legend: bottom, `flex gap-4`

### 예상 탭 Chart
- **Type:** Recharts ComposedChart (Area + Line)
- 예상 잔고: amber dashed line + area fill (`rgba(245,158,11,0.1)`)
- 실제 잔고: green solid line with glow (`#22C55E`, `filter: drop-shadow`)
- 카드 결제일: purple vertical marker
- Legend: `● 예상 잔고  ● 실제 잔고  ● 카드 결제일`

### 비용 탭 Chart
- **Type:** Recharts BarChart (stacked or grouped by category)
- Category colors from badge system (see Badges section)

### Chart Responsive
- lg: full width, 300px height
- md: full width, 250px height
- sm: full width, 200px height, legend below chart in 2-col layout

## Tables

### Table Sorting
- **Fixed chronological order** — no column header sorting
- Reason: running balance column requires time-ordered data

### 실제 탭 Table
| Column | Width | Alignment | Notes |
|--------|-------|-----------|-------|
| 날짜 | 100px | left | MM/DD format |
| 거래 내용 | flex | left | truncate with tooltip |
| 입금 | 120px | right | `--profit-color`, Geist Mono |
| 출금 | 120px | right | `--loss-color`, Geist Mono |
| 잔고 | 120px | right | Geist Mono, running balance |

### Drilldown Specification (카드대금)
- **Pattern:** Accordion expand/collapse within table
- **Icons:** ChevronDown (Lucide) collapsed → ChevronUp expanded
- **Animation:** slide down 200ms ease
- **Nesting:** 3 levels

```
Level 0: 카드대금 — 롯데카드 12월분          (pl-0)
Level 1:   ├─ 하선우 (****1234)              (pl-7 = 28px)
Level 2:   │  ├─ SaaS Anthropic ₩45,000      (pl-12 = 48px)
           │  ├─ 교통비 카카오T ₩3,200
           │  └─ 외 45건 [전체 보기]
```

- Truncation: show first 3 by amount desc, then "외 N건 [전체 보기]" link
- Drilldown persistence: collapsed on tab/month change (reset)
- ARIA: `aria-expanded="true/false"` on parent row, `role="row"` on child rows

### Responsive Table
- lg (1024+): all 5 columns
- md (768): 4 columns (잔고 열 숨김)
- sm (375): 3 columns (날짜 + 거래내용 + 금액), drilldown = accordion below row

## Forecast Input Modal

- Trigger: "항목 추가" button in 예상 탭 header
- Style: shadcn Dialog, max-width 400px

```
┌──── 예상 항목 추가 ────────┐
│ 월:      [2월 ▼]           │
│ 유형:    (●)입금  (○)출금   │
│ 카테고리: [매출 ▼]          │
│ 금액:    [₩              ] │
│ 반복:    [✓] 매월 반복      │
│                            │
│      [취소]  [저장]        │
└────────────────────────────┘
```

- Fields: month (dropdown), type (radio), category (dropdown), amount (number), recurring (checkbox)
- Save: POST /api/forecasts, refresh tab data
- Edit: click existing forecast row → same modal with PUT

## Card Settings Slide-Over

- Trigger: ⚙️ icon in 비용 탭 header
- Style: shadcn Sheet (side="right"), width 400px

```
┌─ 카드 설정 ──────────────┐
│ 롯데카드  결제일: [15일]  │
│ 우리카드  결제일: [25일]  │
│ [카드 추가]              │
│                          │
│ [취소]  [저장]           │
└──────────────────────────┘
```

- Per card: name (text), payment_day (1-31 dropdown), status (active/inactive toggle)
- Save: POST/PUT /api/card-settings

## Formula Display (예상 탭)

- **Collapsible** — "계산 방법 ▸" (collapsed by default)
- Font: Geist Mono 12px, `bg-muted/30`, `rounded-lg`, `p-4`
- Shows: 예상 기말잔고 = 기초 + 입금 - 출금 - 카드사용 + 시차보정

## Comparison Boxes (예상 탭 하단)

- Layout: `grid-cols-2 gap-4` (lg/md), `grid-cols-1` (sm)
- Box 1: 카드 시차 (확정/진행/예상 amounts + 시차 보정 결과)
- Box 2: 예상 vs 실제 (예상 기말, 실제 기말, 차이, 정확도 %)
- Style: `bg-secondary`, `rounded-xl`, `p-4`

## Badges (Category)

| Category | Color | CSS |
|----------|-------|-----|
| 입금 | green | `bg-green-500/12 text-green-400` |
| 출금 | red | `bg-red-500/12 text-red-400` |
| 카드대금 | purple | `bg-purple-500/12 text-purple-400` |
| 선결제 | purple | `bg-purple-500/12 text-purple-400` |
| SaaS | cyan | `bg-cyan-500/12 text-cyan-400` |
| 교통비 | blue | `bg-blue-500/12 text-blue-400` |
| 수수료 | purple | `bg-purple-500/12 text-purple-400` |
| 접대비 | amber | `bg-amber-500/12 text-amber-400` |
| 복리후생 | green | `bg-green-500/12 text-green-400` |
| 기타 | gray | `bg-gray-500/15 text-gray-400` |

- Format: `<Badge variant="outline" className="text-xs px-2 py-0.5">[Label]</Badge>`

## Interaction States (per tab)

| Tab | LOADING | EMPTY | ERROR | SUCCESS | PARTIAL |
|-----|---------|-------|-------|---------|---------|
| 실제 현금흐름 | KPI×4 skeleton + chart skeleton + table skeleton (pulse 1.5s) | "거래 데이터를 업로드해보세요" + 업로드 버튼 (→/upload) | "데이터 로드 실패" + retry 버튼 + 오류 상세 | Normal data display | "카드 데이터 미업로드" amber 배너 + 가용 데이터 |
| 예상 현금흐름 | Same skeleton pattern | "예상 항목을 추가해보세요" + 항목 추가 버튼 | Same pattern | Normal data display | "카드 설정 미완료" amber 배너 + 설정 링크 |
| 비용 (카드) | Same skeleton pattern | "카드 거래 데이터가 없습니다" + 업로드 안내 | Same pattern | Normal data display | "일부 카드만 업로드됨" amber 배너 |

- Skeleton: matches actual content shape (4 cards + chart rect + table rows)
- Empty state: warm message (Geist 16px 500) + primary action button (CTA color)
- Error: `--loss-color` icon (AlertCircle) + specific message + retry Button
- Partial: `--warning-color` Banner at top of tab content

## Accessibility

- Tab navigation: `role="tablist"`, `role="tab"`, `aria-selected`
- Drilldown rows: `aria-expanded`, keyboard Enter/Space to toggle
- Touch targets: minimum 44px height on all interactive elements
- Color contrast: all text meets WCAG AA 4.5:1 on dark backgrounds
- Focus ring: `ring-2 ring-offset-2 ring-offset-background`
- Screen reader: amounts include currency unit in aria-label

## Responsive Breakpoints

| Element | lg (1024+) | md (768) | sm (375) |
|---------|------------|----------|----------|
| KPI cards | grid-cols-4 | grid-cols-2 | grid-cols-2 |
| Chart height | 300px | 250px | 200px |
| Table columns | 5 (all) | 4 (잔고 숨김) | 3 (날짜+내용+금액) |
| Comparison boxes | grid-cols-2 | grid-cols-2 | grid-cols-1 |
| Tab bar | inline pills | inline pills | full-width pills |
| Drilldown | inline expand | inline expand | accordion below-row |
| Legend | inline right | inline right | 2-col below chart |
