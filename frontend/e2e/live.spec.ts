import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'
test.skip(
  !process.env.KATAAI_LIVE_E2E_URL,
  'Explicit live backend/worker opt-in required; no mocks',
)
test('real browser → PostgreSQL → Qwen → Kata → browser', async ({ page }) => {
  test.setTimeout(240000)
  await page.goto('/')
  await page
    .locator('input[type=file]')
    .setInputFiles('../backend/tests/fixtures/qwen_mvp/sales.csv')
  await page
    .getByRole('textbox')
    .fill(
      'What is total revenue in THB, defined as the sum of quantity times unit_price_thb for all orders?',
    )
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/v1/requests') && r.request().method() === 'POST',
  )
  await page.getByTitle('Send question').click()
  const identity = await (await created).json()
  await expect(page.getByRole('status')).toContainText(
    /Completed|Failed|Clarification needed|Unknown|Cancelled/,
    { timeout: 210000 },
  )
  const response = await page.request.get(`/v1/requests/${identity.id}`)
  const record = await response.json()
  await writeFile('/tmp/kataai-browser-live.json', JSON.stringify(record, null, 2))
  await page.screenshot({ path: '/tmp/kataai-browser-live.png', fullPage: true })
  expect(record.status).toBe('completed')
  expect(record.fake).toBe(false)
  expect(record.run_id).toMatch(/^[a-f0-9-]{36}$/)
  expect(record.result.answer).toBe(770)
  expect(record.code).toContain('/inputs/data.csv')
  expect(record.code).toContain('/tmp/result.json')
  await expect(page.getByText(record.code, { exact: true })).toBeVisible()
  await expect(page.getByText(/"answer": 770/)).toBeVisible()
  if (record.answer) await expect(page.getByText(record.answer, { exact: true })).toBeVisible()
})
