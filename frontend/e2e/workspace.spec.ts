import { expect, test } from '@playwright/test'
// Deterministic API mocks exist only in this explicitly identified test suite.
test.skip(!!process.env.KATAAI_LIVE_E2E_URL, 'Use the separate live acceptance case')
test('uploads CSV bytes, creates one request, polls and restores without fake files', async ({
  page,
}) => {
  let creates = 0,
    polls = 0,
    uploads = 0
  await page.route('**/v1/datasets', async (route) => {
    uploads++
    expect(route.request().headers()['x-kataai-request']).toBe('1')
    expect(route.request().headers()['content-type']).toContain('multipart/form-data; boundary=')
    expect(route.request().postDataBuffer()?.toString()).toContain('quantity,unit_price_thb')
    await route.fulfill({ status: 201, json: { dataset_id: 'test-dataset' } })
  })
  await page.route('**/v1/datasets/test-dataset', (route) =>
    route.fulfill({ json: { dataset_id: 'test-dataset' } }),
  )
  await page.route('**/v1/requests', async (route) => {
    creates++
    expect(route.request().headers()['x-kataai-request']).toBe('1')
    expect(route.request().postDataJSON()).toMatchObject({
      schema_version: '1.0',
      dataset_id: 'test-dataset',
      question: 'Total revenue?',
    })
    expect(route.request().postDataJSON().client_request_id).toMatch(/^[a-f0-9-]{36}$/)
    await route.fulfill({ status: 201, json: { id: 'test-request', status: 'queued' } })
  })
  await page.route('**/v1/requests/test-request', async (route) => {
    polls++
    await route.fulfill({
      json: {
        id: 'test-request',
        status: polls === 1 ? 'running' : 'completed',
        fake: false,
        code: '# test generated code',
        result: { answer: 770 },
        answer: 'Test model summary',
        run_id: 'test-run',
      },
    })
  })
  await page.goto('/')
  await page.getByTitle('Load sample sales data').click()
  await page.getByRole('textbox').fill('Total revenue?')
  await page.getByTitle('Send question').click()
  await expect(page.getByText('Completed', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('# test generated code')).toBeVisible()
  await expect(page.getByText(/"answer": 770/)).toBeVisible()
  expect(creates).toBe(1)
  expect(uploads).toBe(1)
  await page.reload()
  await page.getByRole('button', { name: 'Toggle chat history' }).click()
  await page.getByText('Saved analysis').click()
  await expect(page.getByText('Test model summary')).toBeVisible()
  await expect(page.getByText('sample-sales.csv')).toHaveCount(0)
  expect(uploads).toBe(1)
  expect(creates).toBe(1)
  await expect(page.getByText(/Memory:|Guest Kernel:|job-kata-/)).toHaveCount(0)
})
test('backend enforces same-origin writes and serves no private paths', async ({ request }) => {
  expect((await request.post('/v1/requests', { data: {} })).status()).toBe(403)
  expect((await request.get('/', { headers: { Origin: 'http://evil.example' } })).status()).toBe(
    403,
  )
  expect((await request.get('/.mvp-demo/state/kata-runs.sqlite3')).status()).toBe(404)
})
