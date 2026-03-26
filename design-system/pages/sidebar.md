# Sidebar Navigation Design

## Layout
- Desktop: 280px 고정 (항상 펼침, 접힘 없음)
- Mobile (< 768px): hamburger 아이콘 → slide-over overlay (280px)
- 배경: `--color-primary` (#0F172A)
- 높이: 100vh, position fixed

## Logo
- "FinanceOne" 텍스트 로고, Geist 20px bold
- 색상: `--color-text` (#F8FAFC)
- padding: 24px

## Menu Structure (Phase 1)

### 요약 (섹션 레이블)
- 대시보드 → `/` (Lucide: `LayoutDashboard`)
- 현금흐름표 → `/cashflow` (Lucide: `TrendingUp`)

### 데이터 (섹션 레이블)
- 거래내역 → `/transactions` (Lucide: `CreditCard`)
- 업로드 → `/upload` (Lucide: `Upload`)
- Slack 매칭 → `/slack-match` (Lucide: `MessageSquare`)

### 관리 (섹션 레이블)
- 설정 → `/settings` (Lucide: `Settings`)

### P2 메뉴 (disabled 표시)
- 재무제표 → `/statements` (요약 섹션, 회색 텍스트, 클릭 불가)
- 리포트 → `/reports` (요약 섹션, 회색 텍스트, 클릭 불가)
- 내부 계정 → `/accounts/internal` (계정 섹션, 회색 텍스트, 클릭 불가)
- 표준 계정 → `/accounts/standard` (계정 섹션, 회색 텍스트, 클릭 불가)
- 멤버 관리 → `/settings/members` (관리 섹션, 회색 텍스트, 클릭 불가)

## Section Labels
- 10px uppercase, letter-spacing 1.5px, `--neutral-color`
- margin-top: 24px (섹션 간 간격)

## Menu Item
- 높이: 40px
- padding: 8px 16px
- 아이콘: 20px, gap 12px
- 비활성: `--neutral-color` 텍스트
- 호버: `--color-secondary` 배경
- 활성: `--color-cta` (#22C55E) 좌측 3px 보더 + `--color-cta` 텍스트 + `--color-secondary` 배경
- disabled (P2): `--neutral-color` 50% opacity, cursor: not-allowed

## Entity Indicator
- Sidebar 하단에 현재 선택 법인 표시
- 법인명 + 색상 dot (HOI: blue, 코리아: green, 리테일: amber)
- 클릭 시 법인 전환 드롭다운

## Accessibility
- `<nav aria-label="Main navigation">`
- 활성 메뉴: `aria-current="page"`
- 키보드: Tab 이동, Enter 활성화
- 포커스 링: `focus-visible:ring-2 ring-[#22C55E]`
- 모바일 slide-over: `aria-modal="true"`, Escape로 닫기, focus trap
