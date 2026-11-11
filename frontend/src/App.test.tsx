import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('KataAI Gemini-style Chat UI', () => {
  it('renders the welcome screen with KataAI brand and greeting', () => {
    render(<App />)
    expect(screen.getAllByText('KataAI')[0]).toBeInTheDocument()
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()
    expect(
      screen.getByText(/We will test and run the generated Python code inside an isolated/i),
    ).toBeInTheDocument()
    expect(screen.getByTitle('Attach CSV file')).toBeInTheDocument()
  })

  it('populates sample CSV when clicking Use Sample Data and allows typing question', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByTitle('Load sample sales data'))
    expect(screen.getByText('sales_q4.csv')).toBeInTheDocument()

    const textarea = screen.getByPlaceholderText(/Ask a question about this CSV/i)
    await user.type(textarea, 'Which product fell the most?')
    expect(textarea).toHaveValue('Which product fell the most?')
  })

  it('runs the 5-step background pipeline and displays the answer and JSON result', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByTitle('Load sample sales data'))

    const textarea = screen.getByPlaceholderText(/Ask a question about this CSV/i)
    await user.type(
      textarea,
      'Which product had the largest absolute drop in sales from October to November?',
    )

    const sendBtn = screen.getByTitle('Send question')
    await user.click(sendBtn)

    // The user's message should appear in chat
    expect(
      screen.getByText(
        'Which product had the largest absolute drop in sales from October to November?',
      ),
    ).toBeInTheDocument()

    // The pipeline container should appear showing execution steps
    expect(await screen.findByText(/Running Sandbox Pipeline/i)).toBeInTheDocument()

    // Wait for the simulated pipeline to finish and show the answer
    await waitFor(
      () => {
        expect(screen.getByText(/Sandboxed Execution Complete/i)).toBeInTheDocument()
        expect(screen.getByText(/Notebook sales dropped the most/i)).toBeInTheDocument()
        expect(screen.getByText('Generated Python Code')).toBeInTheDocument()
        expect(screen.getByText('Validated JSON Output')).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
  })

  it('resets the chat and returns to welcome screen when clicking reset', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByTitle('Load sample sales data'))
    expect(screen.getByText('sales_q4.csv')).toBeInTheDocument()

    await user.click(screen.getByTitle('Start new analysis'))
    expect(screen.queryByText('sales_q4.csv')).not.toBeInTheDocument()
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()
  })

  it('toggles chat history sidebar and switches between sessions', async () => {
    const user = userEvent.setup()
    render(<App />)

    // Initially in empty state
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()

    // Click the sidebar toggle button or KataAI button to open history
    await user.click(screen.getByTitle('Click to toggle chat history'))

    // Chat history items should be in the sidebar
    expect(screen.getByText('Q4 Sales Drop Analysis')).toBeInTheDocument()
    expect(screen.getByText('Understanding Kata Containers Analogy')).toBeInTheDocument()
    expect(screen.getByText('Policy & Dataset Binding Limits')).toBeInTheDocument()

    // Click on the past session
    await user.click(screen.getByText('Q4 Sales Drop Analysis'))

    // The session's question and answers should now be visible in the chat area
    expect(
      screen.getByText(
        'Which product had the largest absolute drop in sales from October to November?',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/Notebook sales dropped the most/i)).toBeInTheDocument()
    expect(screen.getByText('Generated Python Code')).toBeInTheDocument()

    // Click New Chat to start fresh
    await user.click(screen.getByTitle('Start new chat'))
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()
  })

  it('persists chat sessions to localStorage across component mounts', () => {
    localStorage.clear()
    const { unmount } = render(<App />)

    // Verify localStorage has been populated with default sessions
    const stored = localStorage.getItem('kata_chat_sessions_v1')
    expect(stored).toBeTruthy()
    expect(stored).toContain('Q4 Sales Drop Analysis')
    expect(stored).toContain('Understanding Kata Containers Analogy')

    unmount()

    // Remounting should read from localStorage cleanly
    render(<App />)
    expect(screen.getByText('What do you want to know?')).toBeInTheDocument()
  })
})
