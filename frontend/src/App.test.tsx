import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './lib/api'
vi.mock('./lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  uploadDataset: vi.fn(),
  createRequest: vi.fn(),
  getRequest: vi.fn(),
  getDataset: vi.fn(),
}))
const record = {
  id: 'actual-request',
  status: 'completed' as const,
  fake: false,
  run_id: 'actual-run',
  answer: 'Actual model explanation',
  code: 'actual generated code',
  result: { answer: 770 },
}
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(api.uploadDataset).mockResolvedValue('actual-dataset')
  vi.mocked(api.createRequest).mockResolvedValue(record)
  vi.mocked(api.getDataset).mockResolvedValue({ dataset_id: 'actual-dataset' })
})
async function submit() {
  const user = userEvent.setup()
  await user.click(screen.getByTitle('Load sample sales data'))
  await user.type(screen.getByRole('textbox'), 'Total revenue?')
  await waitFor(() => expect(screen.getByTitle('Send question')).toBeEnabled())
  await user.click(screen.getByTitle('Send question'))
  return user
}
describe('real request UI', () => {
  it('starts without fabricated history or answers', () => {
    render(<App />)
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()
    expect(screen.queryByText(/Notebook sales/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Memory:/)).not.toBeInTheDocument()
  })
  it('renders backend code, JSON, answer and identities', async () => {
    render(<App />)
    await submit()
    expect(await screen.findByText('Actual model explanation')).toBeInTheDocument()
    expect(screen.getByText('actual generated code')).toBeInTheDocument()
    expect(screen.getByText(/"answer": 770/)).toBeInTheDocument()
    expect(api.uploadDataset).toHaveBeenCalledWith(expect.any(File))
    expect(api.createRequest).toHaveBeenCalledWith(
      'actual-dataset',
      'Total revenue?',
      expect.any(String),
    )
    const saved = localStorage.getItem('kata_sessions_v2')!
    expect(saved).toContain('actual-request')
    expect(saved).not.toContain('actual generated code')
    expect(saved).not.toContain('order_id,region')
  })
  it.each(['failed', 'needs_clarification', 'cancelled', 'unknown', 'fake_completed'] as const)(
    'handles %s honestly',
    async (status) => {
      vi.mocked(api.createRequest).mockResolvedValue({ id: 'actual-request', status })
      render(<App />)
      await submit()
      expect(await screen.findByText(api.statusLabel(status))).toBeInTheDocument()
      expect(screen.queryByText('Actual model explanation')).not.toBeInTheDocument()
    },
  )
  it('distinguishes summary failure from execution failure', async () => {
    vi.mocked(api.createRequest).mockResolvedValue({
      ...record,
      answer: null,
      error_code: 'SUMMARY_UNAVAILABLE',
    })
    render(<App />)
    await submit()
    expect(await screen.findByText('Execution completed. Summary unavailable.')).toBeInTheDocument()
    expect(screen.getByText(/"answer": 770/)).toBeInTheDocument()
  })
  it('retries ambiguous creation with the same identity and no duplicate upload', async () => {
    vi.mocked(api.createRequest)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce(record)
    render(<App />)
    const user = await submit()
    await user.click(await screen.findByRole('button', { name: 'Retry same request safely' }))
    expect(await screen.findByText('Actual model explanation')).toBeInTheDocument()
    expect(api.createRequest).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.createRequest).mock.calls[0]).toEqual(
      vi.mocked(api.createRequest).mock.calls[1],
    )
    expect(api.uploadDataset).toHaveBeenCalledTimes(1)
  })
  it('restores backend state without reconstructing CSVs', async () => {
    localStorage.setItem(
      'kata_sessions_v2',
      JSON.stringify([
        {
          id: 'saved',
          requestId: 'actual-request',
          clientRequestId: 'client',
          datasetId: 'actual-dataset',
          question: 'Total?',
        },
      ]),
    )
    vi.mocked(api.getRequest).mockResolvedValue(record)
    render(<App />)
    await userEvent.click(screen.getByText('Saved analysis'))
    expect(await screen.findByText('Actual model explanation')).toBeInTheDocument()
    expect(api.uploadDataset).not.toHaveBeenCalled()
    expect(screen.queryByText('sample-sales.csv')).not.toBeInTheDocument()
  })
  it('polls pending backend states', async () => {
    vi.mocked(api.createRequest).mockResolvedValue({ id: 'actual-request', status: 'queued' })
    vi.mocked(api.getRequest).mockResolvedValue(record)
    render(<App />)
    await submit()
    expect(await screen.findByText('Queued')).toBeInTheDocument()
    expect(
      await screen.findByText('Actual model explanation', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(api.createRequest).toHaveBeenCalledTimes(1)
  })
  it('shows upload failure without creating a request', async () => {
    vi.mocked(api.uploadDataset).mockRejectedValue(new Error('upload unavailable'))
    render(<App />)
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('upload unavailable')
    expect(api.createRequest).not.toHaveBeenCalled()
  })
})

it('blocks duplicate submits while creation is in flight', async () => {
  let resolve!: (value: api.RequestRecord) => void
  vi.mocked(api.createRequest).mockReturnValue(
    new Promise((r) => {
      resolve = r
    }),
  )
  render(<App />)
  const user = await submit()
  await user.type(screen.getByRole('textbox'), 'Total revenue?{Enter}{Enter}')
  expect(api.createRequest).toHaveBeenCalledTimes(1)
  resolve(record)
  expect(await screen.findByText('Actual model explanation')).toBeInTheDocument()
})
it('retains identity through polling outage without resubmission', async () => {
  vi.mocked(api.createRequest).mockResolvedValue({ id: 'retained-request', status: 'queued' })
  vi.mocked(api.getRequest)
    .mockRejectedValueOnce(new Error('network offline'))
    .mockResolvedValueOnce(record)
  render(<App />)
  const user = await submit()
  expect(await screen.findByRole('alert', {}, { timeout: 3000 })).toHaveTextContent(
    'Request identity retained',
  )
  await user.click(screen.getByRole('button', { name: 'Refresh status' }))
  expect(await screen.findByText('Actual model explanation')).toBeInTheDocument()
  expect(api.getRequest).toHaveBeenCalledWith('retained-request')
  expect(api.createRequest).toHaveBeenCalledTimes(1)
})
it('drops a missing historical dataset and requires original reupload', async () => {
  localStorage.setItem(
    'kata_sessions_v2',
    JSON.stringify([
      {
        id: 'saved',
        requestId: 'actual-request',
        clientRequestId: 'client',
        datasetId: 'missing-dataset',
        question: 'Total?',
      },
    ]),
  )
  vi.mocked(api.getRequest).mockResolvedValue(record)
  vi.mocked(api.getDataset).mockRejectedValue(new api.ApiError(404, 'DATASET_NOT_FOUND'))
  render(<App />)
  await userEvent.click(screen.getByText('Saved analysis'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Reupload the original CSV')
  await userEvent.type(screen.getByRole('textbox'), 'Another question')
  expect(screen.getByTitle('Send question')).toBeDisabled()
  expect(api.uploadDataset).not.toHaveBeenCalled()
})
it.each(['MODEL_GENERATION_FAILED', 'EXECUTION_REJECTED'])(
  'shows %s honestly',
  async (error_code) => {
    vi.mocked(api.createRequest).mockResolvedValue({
      id: 'actual-request',
      status: 'failed',
      error_code,
    })
    render(<App />)
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent(error_code)
    expect(screen.getByText('Generated code unavailable.')).toBeInTheDocument()
    expect(screen.getByText('JSON output unavailable.')).toBeInTheDocument()
  },
)
