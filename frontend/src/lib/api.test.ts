import { afterEach, expect, it, vi } from 'vitest'
import { createRequest, getRequest, isPending, statusLabel, uploadDataset } from './api'
afterEach(() => vi.unstubAllGlobals())
it('uploads original file as multipart and uses backend identity', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ dataset_id: 'server-id' }) })
  vi.stubGlobal('fetch', fetch)
  const file = new File(['x\n42\n'], 'real.csv', { type: 'text/csv' })
  expect(await uploadDataset(file)).toBe('server-id')
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe('/v1/datasets')
  expect(options.body.get('file')).toBe(file)
  expect(options.headers).toEqual({ 'X-KataAI-Request': '1' })
})
it('preserves identity on explicit retry', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ id: 'request', status: 'queued' }) })
  vi.stubGlobal('fetch', fetch)
  await createRequest('dataset', 'question', 'stable-client-id')
  await createRequest('dataset', 'question', 'stable-client-id')
  for (const [url, options] of fetch.mock.calls) {
    expect(url).toBe('/v1/requests')
    expect(JSON.parse(options.body)).toEqual({
      schema_version: '1.0',
      client_request_id: 'stable-client-id',
      dataset_id: 'dataset',
      question: 'question',
    })
    expect(options.headers).toEqual({ 'X-KataAI-Request': '1', 'Content-Type': 'application/json' })
  }
})
it.each([
  'completed',
  'failed',
  'needs_clarification',
  'cancelled',
  'unknown',
  'fake_completed',
] as const)('stops polling %s', (status) => {
  expect(isPending(status)).toBe(false)
  expect(statusLabel(status)).toBeTruthy()
})
it('does not retry unavailable backend automatically', async () => {
  const fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ error: { code: 'EXECUTION_UNAVAILABLE' } }),
  })
  vi.stubGlobal('fetch', fetch)
  await expect(getRequest('saved-id')).rejects.toThrow('EXECUTION_UNAVAILABLE')
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('fetches full detail when an idempotent replay is already terminal', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'same-id', status: 'completed' }) })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'same-id', status: 'completed', code: 'actual code' }),
    })
  vi.stubGlobal('fetch', fetch)
  expect((await createRequest('dataset', 'question', 'stable-id')).code).toBe('actual code')
  expect(fetch.mock.calls[1][0]).toBe('/v1/requests/same-id')
})
