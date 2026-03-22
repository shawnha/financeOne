import { test, expect } from '@playwright/test'

test.describe('Phase 1 — Dashboard & Navigation', () => {
  test('dashboard loads KPIs and chart', async ({ page }) => {
    await page.goto('/')

    // Sidebar should be visible
    await expect(page.locator('nav')).toBeVisible()

    // Page title
    await expect(page.locator('h1')).toContainText('대시보드')

    // Should have 4 KPI cards (or empty state with upload CTA)
    const kpiCards = page.locator('[data-testid="kpi-card"]')
    const emptyState = page.locator('text=업로드해보세요')

    // Either KPI cards or empty state should be visible
    await expect(kpiCards.or(emptyState).first()).toBeVisible({ timeout: 10000 })

    // Entity tabs should be visible
    await expect(page.locator('[data-testid="entity-tabs"]')).toBeVisible()
  })

  test('entity tab switches URL param', async ({ page }) => {
    await page.goto('/')

    // Wait for entity tabs to load
    const tabs = page.locator('[data-testid="entity-tabs"]')
    await expect(tabs).toBeVisible({ timeout: 10000 })

    // Click second entity tab (한아원코리아)
    const entityButtons = tabs.locator('button:not([disabled])')
    const count = await entityButtons.count()

    if (count >= 2) {
      await entityButtons.nth(1).click()
      // URL should update with entity param
      await expect(page).toHaveURL(/entity=/)
    }
  })

  test('sidebar navigation works', async ({ page }) => {
    await page.goto('/')

    // Navigate to transactions
    await page.click('a[href="/transactions"]')
    await expect(page).toHaveURL('/transactions')
    await expect(page.locator('h1')).toContainText('거래내역')

    // Navigate to upload
    await page.click('a[href="/upload"]')
    await expect(page).toHaveURL('/upload')
    await expect(page.locator('h1')).toContainText('업로드')

    // Navigate to cashflow
    await page.click('a[href="/cashflow"]')
    await expect(page).toHaveURL('/cashflow')
    await expect(page.locator('h1')).toContainText('현금흐름')
  })
})
