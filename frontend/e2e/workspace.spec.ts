import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
const sample = {
  name: 'sales.csv',
  mimeType: 'text/csv',
  buffer: Buffer.from('product,month,units\nNotebook,October,120\nNotebook,November,80\n'),
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test('opens on a large KataAI hero, then gently scrolls to the form on request', async ({
  page,
}) => {
  const title = page.getByRole('heading', { level: 1, name: 'KataAI' })
  await expect(title).toBeVisible()
  expect(
    await title.evaluate((element) => parseFloat(getComputedStyle(element).fontSize)),
  ).toBeGreaterThan(80)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  expect(
    await page.locator('#workspace').evaluate((element) => element.getBoundingClientRect().top),
  ).toBeGreaterThanOrEqual((page.viewportSize()?.height ?? 0) - 2)
  const started = Date.now()
  await page.getByRole('link', { name: 'Start exploring', exact: true }).click()
  await expect(page.locator('#workspace')).toBeFocused()
  expect(Date.now() - started).toBeGreaterThan(1100)
  await expect(page.getByLabel('Your question', { exact: true })).toBeInViewport()
  await expect(page).toHaveURL(/#workspace$/)
})

test('respects reduced motion when navigating to the form', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('link', { name: 'Start exploring', exact: true }).click()
  await expect(page.locator('#workspace')).toBeFocused({ timeout: 1000 })
  expect(
    await page
      .getByRole('heading', { level: 1 })
      .evaluate((element) => getComputedStyle(element).animationName),
  ).toBe('none')
})

test('lets a manual wheel action interrupt the automatic scroll', async ({ page }) => {
  await page.getByRole('link', { name: 'Start exploring', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
  await page.mouse.wheel(0, 0)
  const position = await page.evaluate(() => window.scrollY)
  await page.waitForTimeout(250)
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - position)).toBeLessThan(3)
  await expect(page).not.toHaveURL(/#workspace$/)
})

test('checks a request locally without displaying a schema or sending data', async ({ page }) => {
  const requests: string[] = []
  const errors: string[] = []
  page.on('request', (request) => {
    if (['fetch', 'xhr'].includes(request.resourceType())) requests.push(request.url())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  await page.getByLabel('Your question', { exact: true }).fill('  Which product dropped most?  ')
  await page.getByLabel('Choose CSV file').setInputFiles(sample)
  await expect(page.getByText('sales.csv', { exact: true })).toBeVisible()
  await page.getByText('Preview dataset', { exact: false }).click()
  await expect(page.getByRole('cell', { name: 'Notebook', exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Check my request' }).click()
  await expect(page.getByRole('heading', { name: 'Your request is ready.' })).toBeVisible()
  await expect(page.locator('pre')).toHaveCount(0)
  await expect(page.getByText(/schema_version|client_request_id|REQUEST INSPECTOR/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Copy JSON' })).toHaveCount(0)
  await expect(
    page.getByText('Nothing has been sent. Backend integration is not connected yet.'),
  ).toBeVisible()
  expect(requests).toEqual([])
  expect(errors).toEqual([])
})

test('shows actionable errors for missing question and CSV', async ({ page }) => {
  await page.getByRole('button', { name: 'Check my request' }).click()
  await expect(page.getByText('Enter a question about your dataset.')).toBeVisible()
  await expect(page.getByText('Add a CSV file before checking your request.')).toBeVisible()
  await expect(page.getByLabel('Your question', { exact: true })).toBeFocused()
  await expect(page.getByTestId('payload-json')).toHaveCount(0)
})

test('accepts a dragged CSV and rejects multiple dropped files', async ({ page }) => {
  const zone = page.locator('.dropzone')
  const single = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['a,b\n1,2'], 'dropped.csv', { type: 'text/csv' }))
    return transfer
  })
  await zone.dispatchEvent('drop', { dataTransfer: single })
  await expect(page.getByText('dropped.csv')).toBeVisible()
  const multiple = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['a\n1'], 'one.csv'))
    transfer.items.add(new File(['b\n2'], 'two.csv'))
    return transfer
  })
  await zone.dispatchEvent('drop', { dataTransfer: multiple })
  await expect(
    page.getByText('Choose one CSV at a time. Multiple files are not supported yet.'),
  ).toBeVisible()
  await expect(page.getByText('dropped.csv')).toHaveCount(0)
})

test('rejects malformed CSV and does not keep a stale valid dataset', async ({ page }) => {
  await page.getByLabel('Choose CSV file').setInputFiles(sample)
  await expect(page.getByText('sales.csv', { exact: true })).toBeVisible()
  await page
    .getByLabel('Choose CSV file')
    .setInputFiles({ name: 'bad.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n1') })
  await expect(page.getByText('Row 2 has 1 field; expected 2.')).toBeVisible()
  await expect(page.getByText('sales.csv', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('payload-json')).toHaveCount(0)
})

test('invalidates prepared payload when inputs change and resets the draft', async ({ page }) => {
  await page.getByRole('button', { name: 'Try an example question' }).click()
  await page.getByRole('button', { name: 'Use sample CSV' }).click()
  await expect(page.getByText('sample-sales.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Check my request' }).click()
  await expect(page.getByRole('heading', { name: 'Your request is ready.' })).toBeVisible()
  await page.getByLabel('Your question', { exact: true }).fill('A different question')
  await expect(page.getByRole('heading', { name: 'Your request is ready.' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Check my request' }).click()
  await page.getByRole('button', { name: 'Remove file' }).click()
  await expect(page.getByTestId('payload-json')).toHaveCount(0)
  await page.getByRole('button', { name: 'Reset draft' }).click()
  await expect(page.getByLabel('Your question', { exact: true })).toHaveValue('')
})

test('renders hostile CSV cells and a hostile question as text, never HTML', async ({ page }) => {
  await page
    .getByLabel('Your question', { exact: true })
    .fill('<img src=x onerror="window.pwned=true">')
  await page.getByLabel('Choose CSV file').setInputFiles({
    name: 'safe.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('column\n<script>window.pwned=true</script>'),
  })
  await expect(page.getByText('safe.csv', { exact: true })).toBeVisible()
  await page.getByText('Preview dataset', { exact: false }).click()
  await expect(page.getByRole('cell', { name: '<script>window.pwned=true</script>' })).toBeVisible()
  await page.getByRole('button', { name: 'Check my request' }).click()
  expect(await page.evaluate(() => Object.hasOwn(window, 'pwned'))).toBe(false)
  expect(await page.locator('img').count()).toBe(0)
})

test('supports keyboard file browsing and has no horizontal page overflow', async ({ page }) => {
  await page.getByRole('button', { name: 'browse files' }).focus()
  const chooser = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  await (await chooser).setFiles(sample)
  await expect(page.getByText('sales.csv', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('keeps the skip link off the content until keyboard focus', async ({ page }) => {
  const link = page.getByRole('link', { name: 'Skip to workspace' })
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  const hiddenBox = await link.boundingBox()
  expect(hiddenBox?.height ?? 0).toBeLessThanOrEqual(1)
  await link.focus()
  await expect(link).toBeFocused()
  expect((await link.boundingBox())?.height ?? 0).toBeGreaterThan(30)
  await page.keyboard.press('Enter')
  await expect(page.locator('#workspace')).toBeFocused()
})

test('passes automated accessibility checks and captures the real interface', async ({
  page,
}, info) => {
  let results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(
    results.violations.map((violation) => ({
      id: violation.id,
      nodes: violation.nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
    })),
  ).toEqual([])
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: `evidence/v2-${info.project.name}-hero.png` })
  await page.screenshot({ path: `evidence/v2-${info.project.name}-landing.png`, fullPage: true })
  await page.getByRole('button', { name: 'Try an example question' }).click()
  await page.getByRole('button', { name: 'Use sample CSV' }).click()
  await expect(page.getByText('sample-sales.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Check my request' }).click()
  results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(
    results.violations.map((violation) => ({
      id: violation.id,
      nodes: violation.nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
    })),
  ).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  await page.screenshot({ path: `evidence/v2-${info.project.name}-checked.png`, fullPage: true })
})
