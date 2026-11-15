import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import ExecutionTimeline from './ExecutionTimeline'
it('shows actual completed latency and active elapsed observation', () => {
  render(
    <ExecutionTimeline
      stages={[
        {
          name: 'generating_code',
          started_at: '2026-11-15T00:00:00Z',
          finished_at: '2026-11-15T00:00:02Z',
          duration_ms: 2000,
          elapsed_ms: 2000,
        },
        {
          name: 'waiting_for_container',
          started_at: '2026-11-15T00:00:02Z',
          finished_at: null,
          duration_ms: null,
          elapsed_ms: 1500,
        },
      ]}
    />,
  )
  expect(screen.getByText('LLM processing')).toBeInTheDocument()
  expect(screen.getByText('2.0 s')).toBeInTheDocument()
  expect(screen.getByText('1.5 s so far')).toBeInTheDocument()
  expect(screen.queryByText('Running in Kata container')).not.toBeInTheDocument()
})
it('keeps historical requests without timing data honest', () => {
  const { container } = render(<ExecutionTimeline />)
  expect(container).toBeEmptyDOMElement()
})
