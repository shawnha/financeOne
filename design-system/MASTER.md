# FinanceOne Design System

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** FinanceOne
**Updated:** 2026-03-22
**Category:** Financial Dashboard / Internal Accounting BPO
**Theme:** Dark Mode (OLED)
**Source:** UUPM (Financial Dashboard + Executive Dashboard + Bento Box Grid + Data-Dense Dashboard)

---

## Patterns (UUPM)

This design system combines 4 UUPM patterns:

1. **Financial Dashboard** — Revenue metrics, P&L visualization, budget tracking, cash flow, audit trail
2. **Executive Dashboard** — Large KPI cards (4-6 max), trend sparklines, at-a-glance insights
3. **Bento Box Grid** — Modular cards with varied sizes (1x1, 2x1, 2x2), asymmetric grid
4. **Data-Dense Dashboard** — Multiple chart widgets, dense tables, minimal padding, maximum data visibility

---

## Color Palette (UUPM: Financial Dashboard Dark)

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Primary | `#0F172A` | `--color-primary` | Headers, sidebar, primary buttons |
| Secondary | `#1E293B` | `--color-secondary` | Cards, elevated surfaces |
| CTA/Accent | `#22C55E` | `--color-cta` | Primary actions, success states |
| Background | `#020617` | `--color-background` | Page background |
| Text | `#F8FAFC` | `--color-text` | Body text |

### Semantic Financial Colors (UUPM: Financial Dashboard)

| Token | Hex | CSS Variable | Usage |
|-------|-----|--------------|-------|
| Profit/Income | `#22C55E` | `--profit-color` | 수입, 증가, 확정 |
| Loss/Expense | `#EF4444` | `--loss-color` | 지출, 감소, 에러 |
| Warning | `#F59E0B` | `--warning-color` | 미확정, AI 저신뢰도 |
| Info/AI | `#6366F1` | `--ai-accent` | AI 매핑, 예측, 정보 |
| Neutral | `#6B7280` | `--neutral-color` | 비활성, 보조 텍스트 |

### Chart Colors (UUPM: Financial Dashboard)

| Token | Hex | Usage |
|-------|-----|-------|
| `--chart-profit` | `#22C55E` | 수입/이익 |
| `--chart-loss` | `#EF4444` | 지출/손실 |
| `--chart-series-1` | `#3B82F6` | 시리즈 1 (Blue) |
| `--chart-series-2` | `#8B5CF6` | 시리즈 2 (Violet) |
| `--chart-series-3` | `#F59E0B` | 시리즈 3 (Amber) |
| `--chart-forecast` | `#8B5CF6` | 예측 (dashed line) |

---

## Typography (UUPM: Financial Trust)

- **Heading Font:** IBM Plex Sans
- **Body Font:** IBM Plex Sans
- **Mono Font:** IBM Plex Mono (금액, 데이터)
- **Mood:** financial, trustworthy, professional, corporate, banking, serious
- **Best For:** Banks, finance, insurance, investment, fintech, enterprise

```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
```

**Tailwind Config:**
```js
fontFamily: {
  sans: ['IBM Plex Sans', 'sans-serif'],
  mono: ['IBM Plex Mono', 'monospace'],
}
```

### Type Scale

| Element | Font | Size | Weight |
|---------|------|------|--------|
| KPI Value | IBM Plex Mono | 48px | 700 |
| H1 (페이지 제목) | IBM Plex Sans | 30px | 700 |
| H2 (섹션 제목) | IBM Plex Sans | 24px | 600 |
| H3 (카드 제목) | IBM Plex Sans | 18px | 600 |
| Body | IBM Plex Sans | 14px | 400 |
| Caption | IBM Plex Sans | 12px | 400 |
| Amount (lg) | IBM Plex Mono | 28px | 700 |
| Amount (md) | IBM Plex Mono | 20px | 600 |
| Amount (sm) | IBM Plex Mono | 14px | 500 |
| Table Data | IBM Plex Mono | 13px | 400 |

### Number Formatting (UUPM: Number Formatting UX)

- KRW: `₩1,234,567` — `Intl.NumberFormat('ko-KR')`, 천 단위 콤마
- USD: `$1,234.56` — `Intl.NumberFormat('en-US')`
- 음수: `--loss-color` + `(₩1,234,567)` 또는 `−₩1,234,567`
- `font-variant-numeric: tabular-nums` 필수 (금액 열 정렬)
- 약어: 1.2K, 1.2M (UUPM: "Use thousand separators or abbreviations")

---

## Spacing (UUPM)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | Tight gaps |
| `--space-sm` | `8px` | Icon gaps, inline spacing |
| `--space-md` | `16px` | Standard padding |
| `--space-lg` | `24px` | Card padding |
| `--space-xl` | `32px` | Section gaps |
| `--space-2xl` | `48px` | Page section margins |

## Shadows (UUPM)

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.3)` | Subtle lift (dark bg) |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.4)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.4)` | Modals, dropdowns |

---

## Layout (UUPM: Data-Dense Dashboard + Bento Box Grid)

| Property | Value |
|----------|-------|
| Max width | 1400px |
| Grid | `grid-template-columns: repeat(12, 1fr)` |
| Grid gap | `16px` (UUPM Bento: `--grid-gap: 16px`) |
| Sidebar | 280px (펼침) / 68px (접힘) |
| Header height | 56px (UUPM: `--header-height: 56px`) |
| Card radius | `12px` (UUPM Bento: `--card-radius`) |
| Card bg | `#1E293B` (secondary) |
| Page bg | `#020617` (background) |
| Table row height | 36px (UUPM: `--table-row-height: 36px`) |

### Bento Grid Card Sizes

| Size | Span | Usage |
|------|------|-------|
| 1x1 | `col-span-3` | KPI card, quick action |
| 2x1 | `col-span-6` | Chart, transaction list |
| 2x2 | `col-span-6 row-span-2` | Cash flow chart |
| 3x1 | `col-span-9` | Wide table |
| 4x1 | `col-span-12` | Full-width table |

---

## Component Specs

### KPI Cards (UUPM: Executive Dashboard)

```
┌─────────────────────────┐
│  Caption (12px, muted)  │
│  ₩12,345,678  (48px)    │
│  ▲ 12.3% vs last month  │
└─────────────────────────┘
```

- KPI 카드 4-6개 max (UUPM: "KPIs 4-6 maximum")
- KPI font-size: 48px (UUPM: `--kpi-font-size: 48px`)
- Sparkline height: 32px (UUPM: `--sparkline-height: 32px`)
- Trend indicators: `--profit-color` for up, `--loss-color` for down
- Number animation: count-up on load (UUPM: "KPI value animations (count-up)")

### Cards (UUPM: Bento Box Grid)

```css
.card {
  background: #1E293B;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.4);
  transition: all 200ms ease;
}
.card:hover {
  box-shadow: 0 10px 15px rgba(0,0,0,0.4);
  transform: scale(1.02);
}
```

### Tables (UUPM: Data-Dense Dashboard + Financial Dashboard)

- Row height: 36px (UUPM: `--table-row-height: 36px`)
- Header: `bg-primary`, font-weight 500, sticky (UUPM: "sticky column headers")
- Amount columns: right-aligned, `tabular-nums`, IBM Plex Mono
- Hover: row highlight
- Zebra striping: alternate row `bg-secondary/50`
- Overflow: `overflow-x-auto` wrapper (UUPM UX: "Table Handling")
- Bulk actions: checkbox column + action bar (UUPM UX: "Bulk Actions")
- Currency formatted, decimals consistent (UUPM: Financial Dashboard checklist)

### Buttons

```css
.btn-primary {
  background: #22C55E;
  color: white;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
.btn-secondary {
  background: transparent;
  color: #F8FAFC;
  border: 1px solid #334155;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Status Badges

| Status | Style |
|--------|-------|
| 확정 (confirmed) | `bg-green-500/20 text-green-400` |
| 미확정 (pending) | `bg-yellow-500/20 text-yellow-400` |
| AI 매핑 | `bg-indigo-500/20 text-indigo-400` + confidence % |
| 에러 | `bg-red-500/20 text-red-400` |

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
}
.modal {
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 16px;
  padding: 32px;
  box-shadow: 0 20px 25px rgba(0,0,0,0.5);
  max-width: 500px;
  width: 90%;
}
```

### Inputs

```css
.input {
  background: #0F172A;
  color: #F8FAFC;
  padding: 12px 16px;
  border: 1px solid #334155;
  border-radius: 8px;
  font-size: 14px;
  transition: border-color 200ms ease;
}
.input:focus {
  border-color: #22C55E;
  outline: none;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.2);
}
```

---

## Charts (UUPM: Chart Recommendations)

| Data Type | Chart | Library |
|-----------|-------|---------|
| 수입 vs 지출 (월별) | Bar Chart (vertical) | Recharts |
| 현금흐름 추이 | Area Chart | Recharts |
| 예측 vs 실제 | Line + Confidence Band (dashed forecast) | Recharts |
| 카테고리별 지출 | Horizontal Bar Chart | Recharts |
| 법인별 비교 | Grouped Bar Chart | Recharts |

**Chart Rules:**
- Tooltip: 반드시 포함
- Legend: 차트 하단
- Grid: dashed, `#334155`
- Animation: 300ms ease-out
- Responsive: `<ResponsiveContainer>` 사용
- Forecast line: dashed (`stroke-dasharray: 5 5`), `--chart-forecast` color
- Anomaly markers: circle + alert annotation

---

## Interaction States (모든 화면 필수)

| State | Implementation |
|-------|----------------|
| LOADING | Skeleton UI (card/table shaped, pulse 1.5s) |
| EMPTY | Warm message + CTA button ("데이터를 업로드해보세요") |
| ERROR | Specific error message + retry button |
| SUCCESS | Normal data display |
| PARTIAL | Warning banner (`--warning-color`) + available data |

---

## Animation (UUPM: Dark Mode + Financial Dashboard)

| Element | Duration | Effect |
|---------|----------|--------|
| Page transition | 200ms ease-out | opacity + translateY 4px |
| Card hover | 200ms ease | shadow elevation + scale(1.02) |
| Skeleton pulse | 1.5s infinite | opacity 0.5 → 1 |
| Chart entry | 300ms ease-out | draw animation |
| KPI count-up | 600ms | number animation on load |
| Button feedback | 80-150ms | translateY(-1px) |
| Alert pulse | 2s infinite | glow effect for critical items |
| Key effect | — | Minimal glow: `text-shadow: 0 0 10px` on key values |
| `prefers-reduced-motion` | — | respect always |

---

## Anti-Patterns (UUPM + Financial)

- Emojis as icons — use Lucide SVG only
- Missing `cursor: pointer` on clickable elements
- Layout-shifting hovers (avoid large scale transforms that shift layout)
- Low contrast text (maintain 4.5:1 minimum)
- Instant state changes without transitions (150-300ms minimum)
- Invisible focus states
- Light mode default (this is a dark-mode-first app)
- Slow rendering / heavy animations on data tables
- Unformatted numbers (always use Intl.NumberFormat)
- Wide tables breaking layout (use overflow-x-auto)
- Single row actions only (provide bulk actions)

---

## Pre-Delivery Checklist (UUPM)

Before delivering any UI code, verify:

- [ ] No emojis used as icons (Lucide SVG only)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum on dark background
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
- [ ] Currency formatted (`Intl.NumberFormat`)
- [ ] Decimals consistent (KRW: 0, USD: 2)
- [ ] P&L clearly distinguished (green/red)
- [ ] Budget variance shown where applicable
- [ ] Tables: sortable, overflow-x-auto, sticky headers
- [ ] All 5 interaction states implemented (loading/empty/error/success/partial)
- [ ] Export to Excel functionality where applicable
