export type RequestStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'needs_clarification'
  | 'cancel_requested'
  | 'cancelled'
  | 'unknown'
  | 'fake_completed'
export type ExecutionStage = {
  name: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  elapsed_ms: number
  outcome?: string
}
export type RequestRecord = {
  execution_stages?: ExecutionStage[]
  observed_at?: string
  id: string
  status: RequestStatus
  dataset_id?: string
  question?: string
  fake?: boolean
  answer?: string | null
  result?: Record<string, unknown> | unknown[] | null
  code?: string | null
  run_id?: string | null
  error_code?: string | null
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(`${code} (HTTP ${status})`)
  }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    cache: 'no-store',
    signal: AbortSignal.timeout(init?.body instanceof FormData ? 70000 : 20000),
    credentials: 'same-origin',
    headers: { 'X-KataAI-Request': '1', ...init?.headers },
  })
  const data = await response.json()
  if (!response.ok) throw new ApiError(response.status, data.error?.code ?? 'API_ERROR')
  return data as T
}
export async function uploadDataset(file: File) {
  const body = new FormData()
  body.append('file', file)
  const data = await request<{ dataset_id: string }>('/v1/datasets', { method: 'POST', body })
  if (!data.dataset_id)
    throw new Error('Upload response missing dataset identity. Reupload explicitly.')
  return data.dataset_id
}
export async function createRequest(datasetId: string, question: string, clientRequestId: string) {
  const created = await request<RequestRecord>('/v1/requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      schema_version: '1.0',
      client_request_id: clientRequestId,
      dataset_id: datasetId,
      question,
    }),
  })
  // An idempotent replay can already be terminal; POST omits generated code.
  if (!isPending(created.status)) {
    try {
      return await getRequest(created.id)
    } catch {
      return created
    }
  }
  return created
}
export const getRequest = (id: string) =>
  request<RequestRecord>(`/v1/requests/${encodeURIComponent(id)}`)
export const getDataset = (id: string) =>
  request<{ dataset_id: string }>(`/v1/datasets/${encodeURIComponent(id)}`)
export const isPending = (status: RequestStatus) =>
  ['queued', 'running', 'cancel_requested'].includes(status)
export const statusLabel = (status: RequestStatus) =>
  ({
    queued: 'Queued',
    running: 'Processing',
    completed: 'Completed',
    failed: 'Failed',
    needs_clarification: 'Clarification needed',
    cancel_requested: 'Cancellation requested',
    cancelled: 'Cancelled',
    unknown: 'Unknown — execution may have occurred. Do not resubmit.',
    fake_completed: 'Legacy fake execution — not a real result',
  })[status] ?? 'Unsupported backend status — do not resubmit'
