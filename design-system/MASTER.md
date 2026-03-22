# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** FinanceOne
**Updated:** 2026-03-22
**Category:** Financial Dashboard / Internal Accounting BPO
**Base:** UUPM + FinanceOne PRD custom overrides
**Patterns:** Financial Dashboard (#9), Bento Box Grid (#21), Executive Dashboard (#3)

---

## Global Rules

### Color Palette — Light Mode (Default)

| Role | HSL | Hex | CSS Variable |
|------|-----|-----|--------------|
| Primary | 240 5.9% 10% | `#18181B` | `--primary` |
| Primary Foreground | 0 0% 98% | `#FAFAFA` | `--primary-foreground` |
| Background | 0 0% 100% | `#FFFFFF` | `--background` |
| Foreground | 240 10% 3.9% | `#09090B` | `--foreground` |
| Card | 0 0% 100% | `#FFFFFF` | `--card` |
| Muted | 240 4.8% 95.9% | `#F4F4F5` | `--muted` |
| Muted Foreground | 240 3.8% 46.1% | `#71717A` | `--muted-foreground` |
| Border | 240 5.9% 90% | `#E4E4E7` | `--border` |
| Destructive | 0 84.2% 60.2% | `#EF4444` | `--destructive` |

### Color Palette — Dark Mode (Toggle)

| Role | HSL | Hex |
|------|-----|-----|
| Primary | 0 0% 98% | `#FAFAFA` |
| Background | 240 10% 3.9% | `#09090B` |
| Foreground | 0 0% 98% | `#FAFAFA` |
| Card | 240 10% 3.9% | `#09090B` |
| Muted | 240 3.7% 15.9% | `#27272A` |
| Border | 240 3.7% 15.9% | `#27272A` |

### Semantic Colors (Financial)

| Token | Light Hex | Usage |
|-------|-----------|-------|
| `--success` | `#16A34A` | 수입, 증가, 확정 |
| `--danger` | `#EF4444` | 지출, 감소, 에러 |
| `--warning` | `#F59E0B` | 주의, 미확정, AI 저신뢰도 |
| `--info` | `#3B82F6` | 정보, AI 매핑, 링크 |

### Chart Colors (색맹 배려 — IBM Design)

| Token | Hex | Usage |
|-------|-----|-------|
| `--chart-1` | `#6366F1` | 시리즈 1 (Indigo) |
| `--chart-2` | `#22C55E` | 시리즈 2 (Green) |
| `--chart-3` | `#F59E0B` | 시리즈 3 (Amber) |
| `--chart-4` | `#EF4444` | 시리즈 4 (Red) |
| `--chart-5` | `#8B5CF6` | 시리즈 5 (Violet) |

---

### Typography (UUPM: IBM Plex Sans)

- **Heading Font:** IBM Plex Sans
- **Body Font:** IBM Plex Sans
- **Mono Font:** IBM Plex Mono (금액, 코드)
- **Mood:** financial, trustworthy, professional, corporate, banking
- **Google Fonts:** [IBM Plex Sans + Mono](https://fonts.google.com/share?selection.family=IBM+Plex+Sans:wght@300;400;500;600;700|IBM+Plex+Mono:wght@400;500;600)

```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
```

| Element | Font | Size | Weight | Line Height |
|---------|------|------|--------|-------------|
| H1 (페이지 제목) | IBM Plex Sans | 30px | 700 | 1.2 |
| H2 (섹션 제목) | IBM Plex Sans | 24px | 600 | 1.3 |
| H3 (카드 제목) | IBM Plex Sans | 18px | 600 | 1.4 |
| Body | IBM Plex Sans | 14px | 400 | 1.5 |
| Caption | IBM Plex Sans | 12px | 400 | 1.5 |
| Amount (lg) | IBM Plex Mono | 28px | 700 | 1.2 |
| Amount (md) | IBM Plex Mono | 20px | 600 | 1.3 |
| Amount (sm) | IBM Plex Mono | 14px | 500 | 1.5 |

### Number Formatting

- KRW: `₩1,234,567` (천 단위 콤마)
- USD: `$1,234.56`
- 음수: 빨간색 + `(₩1,234,567)` 또는 `−₩1,234,567`
- Tabular Nums: `font-variant-numeric: tabular-nums` (숫자 정렬)

---

### Spacing Variables (UUPM)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Card padding, section padding |
| `--space-xl` | `32px` / `2rem` | Section gaps |
| `--space-2xl` | `48px` / `3rem` | Page section margins |

### Shadow Depths (UUPM)

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Featured cards |

---

## Layout

- **Max width:** 1400px (container)
- **Sidebar:** 280px (펼침) / 68px (접힘)
- **Grid:** 12 column, 24px gap
- **Dashboard cards:** Bento Grid — 1x1, 2x1, 2x2 조합
- **Breakpoints:** sm 640px, md 768px, lg 1024px, xl 1280px, 2xl 1400px

---

## Component Specs

### Cards (Bento Grid)

```css
.card {
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  padding: 24px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 200ms ease;
}
.card:hover {
  box-shadow: var(--shadow-md);
}
```

### Tables (Dense Financial Data)

- Row height: 40px
- Header: `bg-muted`, font-weight 500
- Amount columns: right-aligned, `font-variant-numeric: tabular-nums`, IBM Plex Mono
- Hover: `bg-accent`
- Zebra striping: even rows `bg-muted/50`

### Buttons (shadcn/ui)

- Primary: 확정, 저장, 제출
- Secondary: 취소, 닫기
- Outline: 필터, 토글
- Destructive: 삭제, 초기화
- Ghost: 네비게이션, 더보기
- All buttons: `cursor: pointer`, transition 200ms

### Status Badges

| Status | Style |
|--------|-------|
| 확정 (confirmed) | green bg + text |
| 미확정 (pending) | yellow bg + text |
| AI 매핑 | blue bg + confidence % |
| 에러 | red bg + text |

### Charts (Recharts)

- Tooltip: 반드시 포함
- Legend: 차트 하단
- Grid: dashed, `var(--border)` color
- Animation: 300ms ease-out
- Responsive: `<ResponsiveContainer>` 사용
- Color palette: chart-1 through chart-5

---

## Interaction States (모든 화면 필수)

| State | Implementation |
|-------|----------------|
| LOADING | Skeleton UI (카드/테이블 형태에 맞게) |
| EMPTY | Warm message + CTA button |
| ERROR | Specific error + retry/alternative |
| SUCCESS | Normal data display |
| PARTIAL | Warning banner + available data |

---

## Animation

- Page transition: 200ms ease-out (opacity + translateY 4px)
- Card hover: 150ms (shadow elevation only, no translateY)
- Skeleton pulse: 1.5s infinite
- Chart entry: 300ms ease-out
- Button click feedback: 80-150ms
- `prefers-reduced-motion`: respect always

---

## Anti-Patterns (Do NOT Use)

- AI purple/pink gradients (뱅킹 앱에 부적합)
- Bubble/rounded playful UI (신뢰감 저하)
- Excessive animation on financial data
- Low contrast text (4.5:1 미달)
- Touch targets < 44px
- Emojis as icons (use Lucide SVG)
- Missing `cursor: pointer` on clickable elements
- Layout-shifting hovers (scale transforms)
- Instant state changes without transitions
- `text-shadow: glow` effects (OLED 전용이므로 사용 금지)

---

## Pre-Delivery Checklist (UUPM)

Before delivering any UI code, verify:

- [ ] No emojis used as icons (Lucide only)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum (light + dark)
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
- [ ] Amount columns: right-aligned, tabular-nums, IBM Plex Mono
- [ ] All 5 interaction states implemented (loading/empty/error/success/partial)
- [ ] Financial data: KRW/USD formatting correct
- [ ] Negative amounts: red color
