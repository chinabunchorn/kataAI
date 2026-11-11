import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('KataAI landing page', () => {
  it('opens with the KataAI wordmark and an invitation to the workspace, not a developer inspector', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'KataAI' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start exploring' })).toHaveAttribute(
      'href',
      '#workspace',
    )
    expect(screen.queryByText('REQUEST INSPECTOR')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copy JSON' })).not.toBeInTheDocument()
  })

  it('checks the real inputs and shows a simple confirmation without rendering a payload schema', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Your question'), 'Which product fell most?')
    await user.upload(
      screen.getByLabelText('Choose CSV file'),
      new File(['product,units\nPen,45'], 'sales.csv', { type: 'text/csv' }),
    )
    await screen.findByText('sales.csv')
    await user.click(screen.getByRole('button', { name: 'Check my request' }))
    expect(
      await screen.findByRole('heading', { name: 'Your request is ready.' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Nothing has been sent. Backend integration is not connected yet.'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('payload-json')).not.toBeInTheDocument()
    expect(screen.queryByText(/schema_version|client_request_id/)).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Your question'), ' More detail.')
    expect(
      screen.queryByRole('heading', { name: 'Your request is ready.' }),
    ).not.toBeInTheDocument()
  })

  it('retains usable sample inputs and reset without any fake analysis', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Try an example question' }))
    await user.click(screen.getByRole('button', { name: 'Use sample CSV' }))
    await screen.findByText('sample-sales.csv')
    await user.click(screen.getByRole('button', { name: 'Check my request' }))
    await screen.findByRole('heading', { name: 'Your request is ready.' })
    await user.click(screen.getByRole('button', { name: 'Reset draft' }))
    expect(screen.getByLabelText('Your question')).toHaveValue('')
    expect(screen.queryByText('sample-sales.csv')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Your request is ready.' }),
    ).not.toBeInTheDocument()
  })
})
