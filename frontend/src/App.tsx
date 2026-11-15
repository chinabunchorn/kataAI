import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import {
  AlertCircle,
  ArrowUp,
  Carrot,
  Clock,
  Database,
  FileSpreadsheet,
  LoaderCircle,
  MessageSquare,
  PanelLeft,
  PanelLeftClose,
  Plus,
  RotateCcw,
  Table,
  Trash2,
  X,
} from 'lucide-react'
import { inspectCsv } from './lib/csv'
import type { CsvDataset } from './lib/csv'
import { validateQuestion } from './lib/submission'
import {
  ApiError,
  createRequest,
  getDataset,
  getRequest,
  isPending,
  statusLabel,
  uploadDataset,
} from './lib/api'
import type { RequestRecord } from './lib/api'
import ExecutionTimeline, { stageLabel } from './lib/ExecutionTimeline'

const DEFAULT_SAMPLE_FILE = new File(
  [
    'order_id,region,quantity,unit_price_thb\n1,East,2,100\n2,East,1,150\n3,East,3,40\n4,West,4,75\n',
  ],
  'sample-sales.csv',
  { type: 'text/csv' },
)
const STORAGE_KEY = 'kata_sessions_v2'
type ChatMessage = {
  id: string
  sender: 'user' | 'assistant'
  question: string
  dataset?: CsvDataset
  record?: RequestRecord
  notice?: string
  error?: string
  retry?: boolean
}
type SavedSession = {
  id: string
  datasetId?: string
  requestId?: string
  clientRequestId: string
  question: string
}
type ChatSession = SavedSession & { title: string; messages: ChatMessage[] }
function persistIntent(session: SavedSession) {
  // Write correlation before POST: a reload must never manufacture a new identity.
  // Keep only request inputs/IDs; never persist preview, generated code or output.
  const saved: SavedSession[] = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify([session, ...saved.filter((s) => s.id !== session.id)]),
  )
}
function loadSessions(): ChatSession[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as SavedSession[]
    return saved
      .filter(
        (s) =>
          typeof s.id === 'string' &&
          typeof s.clientRequestId === 'string' &&
          typeof s.question === 'string',
      )
      .map((s) => ({
        ...s,
        title: 'Saved analysis',
        messages: [
          { id: `${s.id}-user`, sender: 'user', question: s.question },
          {
            id: s.id,
            sender: 'assistant',
            question: '',
            notice: 'Refresh to retrieve backend state.',
            retry: !s.requestId && !!s.datasetId,
          },
        ],
      }))
  } catch {
    return []
  }
}
export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(loadSessions)
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const current = sessions.find((s) => s.id === currentSessionId)
  const messages = current?.messages ?? []
  const activeDatasetId = current?.datasetId
  const [inputText, setInputText] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [dataset, setDataset] = useState<CsvDataset | null>(null)
  const [csvError, setCsvError] = useState<string | null>(null)
  const [isProcessingCsv, setIsProcessingCsv] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [showCsvPreviewModal, setShowCsvPreviewModal] = useState(false)
  const busy = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const chatBottomRef = useRef<HTMLDivElement>(null)
  function update(id: string, change: Partial<ChatMessage>, extra: Partial<ChatSession> = {}) {
    setSessions((prev) =>
      prev.map((s) =>
        s.id === id
          ? {
              ...s,
              ...extra,
              messages: s.messages.map((m) => (m.sender === 'assistant' ? { ...m, ...change } : m)),
            }
          : s,
      ),
    )
  }
  useEffect(() => {
    try {
      localStorage.removeItem('kata_chat_sessions_v1')
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(
          sessions.map(({ id, datasetId, requestId, clientRequestId, question }) => ({
            id,
            datasetId,
            requestId,
            clientRequestId,
            question,
          })),
        ),
      )
    } catch {
      /* Storage is optional. */
    }
  }, [sessions])
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages])
  useEffect(() => {
    if (!selectedFile) {
      setDataset(null)
      setIsProcessingCsv(false)
      return
    }
    let active = true
    setIsProcessingCsv(true)
    inspectCsv(selectedFile)
      .then((parsed) => {
        if (active) {
          setDataset(parsed)
          setCsvError(null)
        }
      })
      .catch((e: Error) => {
        if (active) {
          setDataset(null)
          setCsvError(e.message)
        }
      })
      .finally(() => {
        if (active) setIsProcessingCsv(false)
      })
    return () => {
      active = false
    }
  }, [selectedFile])
  async function refresh(id: string) {
    const session = sessions.find((s) => s.id === id)
    if (!session?.requestId) return
    try {
      update(id, {
        record: await getRequest(session.requestId),
        error: undefined,
        notice: undefined,
        retry: false,
      })
    } catch (e) {
      update(id, {
        error: `${String(e)}. Request identity retained. Refresh to reconnect; do not resubmit.`,
      })
    }
  }
  const pending = current?.messages.some((m) => m.record && isPending(m.record.status))
  useEffect(() => {
    if (!currentSessionId || !pending) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      await refresh(currentSessionId)
      if (!stopped) timer = setTimeout(poll, 1500)
    }
    timer = setTimeout(poll, 1500)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [currentSessionId, current?.requestId, pending])
  function handleFileSelect(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) {
      setDataset(null)
      setSelectedFile(file)
    }
  }
  function handleRemoveFile() {
    setSelectedFile(null)
    setDataset(null)
    setCsvError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }
  function handleUseSampleCsv() {
    setSelectedFile(DEFAULT_SAMPLE_FILE)
  }
  async function handleSelectSession(id: string) {
    setCurrentSessionId(id)
    handleRemoveFile()
    setInputText('')
    setIsSidebarOpen(false)
    const session = sessions.find((s) => s.id === id)
    if (session?.requestId) void refresh(id)
    if (session?.datasetId) {
      try {
        await getDataset(session.datasetId)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404)
          update(
            id,
            { error: 'Previous dataset unavailable. Reupload the original CSV.' },
            { datasetId: undefined },
          )
        else
          update(id, {
            error: 'Dataset availability could not be verified. Refresh before submitting.',
          })
      }
    }
  }
  function handleStartNewChat() {
    setCurrentSessionId(null)
    setInputText('')
    handleRemoveFile()
    setIsSidebarOpen(false)
  }
  function handleDeleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (currentSessionId === id) handleStartNewChat()
  }
  async function retryCreation(id: string) {
    const s = sessions.find((s) => s.id === id)
    if (!s?.datasetId || busy.current) return
    busy.current = true
    setIsSending(true)
    try {
      persistIntent({
        id: s.id,
        datasetId: s.datasetId,
        requestId: s.requestId,
        clientRequestId: s.clientRequestId,
        question: s.question,
      })
      const record = await createRequest(s.datasetId, s.question, s.clientRequestId)
      update(id, { record, retry: false, error: undefined }, { requestId: record.id })
    } catch (e) {
      update(id, {
        error: `${String(e)}. Creation may have committed. Retry only with this same identity.`,
        retry: true,
      })
    } finally {
      busy.current = false
      setIsSending(false)
    }
  }
  async function handleSendMessage(event?: FormEvent) {
    event?.preventDefault()
    if (busy.current || isProcessingCsv || (selectedFile && !dataset)) return
    const validation = validateQuestion(inputText)
    if (validation || (!dataset && !activeDatasetId)) {
      setCsvError(validation ?? 'Attach the original CSV before submitting.')
      return
    }
    if (
      current?.messages.some(
        (m) =>
          m.retry ||
          (!!current.requestId && !m.record && m.sender === 'assistant') ||
          (m.record && (isPending(m.record.status) || m.record.status === 'unknown')),
      )
    ) {
      setCsvError('This analysis is pending or uncertain. Refresh or retry its existing identity.')
      return
    }
    busy.current = true
    setIsSending(true)
    const id = crypto.randomUUID(),
      clientRequestId = crypto.randomUUID(),
      question = inputText.trim()
    const session: ChatSession = {
      id,
      clientRequestId,
      question,
      title: question.length > 40 ? `${question.slice(0, 40)}…` : question,
      datasetId: selectedFile ? undefined : activeDatasetId,
      messages: [
        { id: `${id}-user`, sender: 'user', question, dataset: dataset ?? undefined },
        {
          id,
          sender: 'assistant',
          question: '',
          notice: dataset ? 'Uploading dataset' : 'Creating request',
        },
      ],
    }
    setSessions((prev) => [session, ...prev])
    setCurrentSessionId(id)
    setInputText('')
    let datasetId = session.datasetId
    try {
      if (!datasetId) {
        datasetId = await uploadDataset(dataset!.file)
        update(id, { notice: 'Creating request' }, { datasetId })
      }
      persistIntent({ id, datasetId, clientRequestId, question })
      const record = await createRequest(datasetId, question, clientRequestId)
      update(id, { record, notice: undefined }, { requestId: record.id })
    } catch (e) {
      update(id, {
        error: datasetId
          ? `${String(e)}. Creation may have committed. Use Retry same request safely.`
          : `${String(e)}. Upload outcome uncertain. Reattach the original file and explicitly start a new analysis.`,
        notice: undefined,
        retry: !!datasetId,
      })
    } finally {
      busy.current = false
      setIsSending(false)
    }
  }
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void handleSendMessage()
    }
  }
  const inputForm = (
    <form className="gemini-input-card" onSubmit={handleSendMessage}>
      {/* Attached CSV Chip inside the pill */}
      {selectedFile && (
        <div className="input-file-chip">
          <FileSpreadsheet size={16} className="file-chip-icon" />
          <div className="file-chip-info">
            <span className="file-chip-name">{selectedFile.name}</span>
            {dataset && (
              <span className="file-chip-details">
                ({dataset.rowCount} rows • {dataset.headers.length} cols)
              </span>
            )}
          </div>
          <button
            type="button"
            className="file-chip-remove"
            onClick={handleRemoveFile}
            title="Remove file"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {csvError && (
        <div className="input-error-banner">
          <AlertCircle size={14} />
          <span>{csvError}</span>
        </div>
      )}

      <div className="input-row">
        {/* CSV File Input Button (Plus Icon like Gemini) */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />

        <button
          type="button"
          className="attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Attach CSV file"
          disabled={isProcessingCsv || isSending}
        >
          <Plus size={20} />
        </button>

        {/* Prompt Textarea */}
        <textarea
          ref={textareaRef}
          rows={1}
          className="gemini-textarea"
          placeholder={
            selectedFile
              ? 'Ask a question about this CSV...'
              : 'Attach a CSV file and ask a question...'
          }
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
        />

        {/* Send Button */}
        <button
          type="submit"
          className={`send-btn ${inputText.trim() ? 'active' : ''}`}
          disabled={
            !inputText.trim() || isSending || isProcessingCsv || (!dataset && !activeDatasetId)
          }
          title="Send question"
        >
          {isSending ? <LoaderCircle size={18} className="spinning" /> : <ArrowUp size={20} />}
        </button>
      </div>
    </form>
  )

  return (
    <div className="gemini-app">
      {/* Mobile Backdrop */}
      {isSidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setIsSidebarOpen(false)}
          role="presentation"
        />
      )}

      {/* Left Sidebar Drawer (Gemini style) */}
      <aside
        className={`gemini-sidebar ${isSidebarOpen ? 'open' : 'closed'}`}
        aria-label="Chat history"
      >
        <div className="sidebar-header">
          <button
            type="button"
            className="sidebar-brand-btn"
            onClick={() => setIsSidebarOpen(false)}
            title="Close sidebar"
          >
            <span className="sidebar-carrot">
              <Carrot size={18} />
            </span>
            <span className="sidebar-brand-title">KataAI</span>
          </button>

          <button
            type="button"
            className="sidebar-close-btn"
            onClick={() => setIsSidebarOpen(false)}
            title="Collapse sidebar"
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        {/* New Chat Button (Pill style like Gemini แชทใหม่) */}
        <div className="sidebar-action-section">
          <button
            type="button"
            className="sidebar-new-chat-btn"
            onClick={handleStartNewChat}
            title="Start new chat"
          >
            <Plus size={16} />
            <span>New Chat</span>
          </button>
        </div>

        {/* Chat History List */}
        <div className="sidebar-history-container">
          <div className="sidebar-history-header">
            <span className="sidebar-history-label">Recent</span>
            <Clock size={13} className="sidebar-history-clock" />
          </div>

          <div className="sidebar-history-list">
            {sessions.map((session) => (
              <div
                key={session.id}
                className={`history-item ${session.id === currentSessionId ? 'active' : ''}`}
                onClick={() => handleSelectSession(session.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    void handleSelectSession(session.id)
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <MessageSquare size={15} className="history-item-icon" />
                <span className="history-item-title" title={session.title}>
                  {session.title}
                </span>
                {sessions.length > 1 && (
                  <button
                    type="button"
                    className="history-item-delete"
                    onClick={(e) => handleDeleteSession(session.id, e)}
                    title="Delete chat"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* Main App Body */}
      <div className="gemini-app-body">
        {/* Top Navigation Bar */}
        <header className="gemini-header">
          <div className="header-left">
            <button
              type="button"
              className="sidebar-toggle-btn"
              onClick={() => setIsSidebarOpen((prev) => !prev)}
              title={isSidebarOpen ? 'Close sidebar' : 'Open chat history'}
              aria-label="Toggle chat history"
            >
              <PanelLeft size={19} />
            </button>

            <button
              type="button"
              className="brand-badge-btn"
              onClick={() => setIsSidebarOpen((prev) => !prev)}
              title="Click to toggle chat history"
            >
              <span className="brand-logo">KataAI</span>
            </button>
          </div>

          <div className="header-actions">
            {selectedFile ? (
              <button
                type="button"
                className="action-pill-btn"
                onClick={() => setShowCsvPreviewModal(true)}
                title="Preview attached CSV"
              >
                <Table size={14} />
                <span>Preview CSV</span>
              </button>
            ) : (
              <button
                type="button"
                className="action-pill-btn"
                onClick={handleUseSampleCsv}
                title="Load sample sales data"
              >
                <Database size={14} />
                <span>Use Sample Data</span>
              </button>
            )}

            <button
              type="button"
              className="action-icon-btn"
              onClick={handleStartNewChat}
              title="Start new analysis"
            >
              <RotateCcw size={16} />
            </button>
          </div>
        </header>

        {/* Main Chat Content Area */}
        <main className="gemini-main">
          {messages.length === 0 ? (
            /* Empty State - Gemini Welcome Screen */
            <div className="gemini-hero">
              <div className="hero-sparkle">
                <Carrot size={38} className="sparkle-icon" />
              </div>

              <h1 className="hero-greeting">What do you want to know?</h1>
              <p className="hero-subtext">
                Ask any question about your dataset. We will test and run the generated Python code
                inside an isolated <strong>Kata Container</strong> on the approved remote runtime.
                Results appear only after the backend responds.
              </p>

              <div className="hero-input-wrapper">{inputForm}</div>
            </div>
          ) : (
            /* Active Chat Stream */
            <div className="chat-stream">
              {messages.map((msg) => (
                <div key={msg.id} className={`chat-row ${msg.sender}`}>
                  {msg.sender === 'user' ? (
                    <div className="user-message-container">
                      {msg.dataset && (
                        <div className="attached-dataset-badge">
                          <FileSpreadsheet size={15} />
                          <span className="dataset-name">{msg.dataset.file.name}</span>
                          <span className="dataset-meta">
                            {msg.dataset.rowCount} rows • {msg.dataset.headers.length} cols
                          </span>
                        </div>
                      )}
                      <div className="user-bubble">{msg.question}</div>
                    </div>
                  ) : (
                    <div className="assistant-message-container">
                      <div className="assistant-avatar">
                        <Carrot size={18} />
                      </div>

                      <div className="assistant-content">
                        <div className="pipeline-container execution-status" role="status">
                          {msg.record
                            ? msg.record.fake
                              ? 'Legacy fake execution — not a real result'
                              : `${statusLabel(msg.record.status)}${msg.record.status === 'running' && msg.record.execution_stages?.at(-1)?.finished_at === null ? ` — ${stageLabel(msg.record.execution_stages.at(-1)!.name)}` : ''}`
                            : msg.notice}
                        </div>
                        {msg.record &&
                          !msg.record.fake &&
                          msg.record.status !== 'fake_completed' && (
                            <ExecutionTimeline stages={msg.record.execution_stages} />
                          )}
                        {msg.error && <p role="alert">{msg.error}</p>}
                        {current?.requestId && (
                          <button type="button" onClick={() => refresh(currentSessionId!)}>
                            Refresh status
                          </button>
                        )}
                        {msg.retry && (
                          <button
                            type="button"
                            disabled={isSending}
                            onClick={() => retryCreation(currentSessionId!)}
                          >
                            Retry same request safely
                          </button>
                        )}
                        {msg.record &&
                          msg.record.status !== 'fake_completed' &&
                          !msg.record.fake && (
                            <div className="result-card">
                              <p>Request ID: {msg.record.id}</p>
                              {msg.record.run_id && <p>Run ID: {msg.record.run_id}</p>}
                              {msg.record.error_code && <p role="alert">{msg.record.error_code}</p>}
                              <div className="result-answer">
                                {msg.record.answer ??
                                  (msg.record.status === 'completed'
                                    ? 'Execution completed. Summary unavailable.'
                                    : 'Answer unavailable.')}
                              </div>
                              <div className="json-box">
                                <div className="json-header">Generated Python Code</div>
                                <pre className="json-code">
                                  {msg.record.code ?? 'Generated code unavailable.'}
                                </pre>
                              </div>
                              <div className="json-box">
                                <div className="json-header">Validated JSON Output</div>
                                <pre className="json-code">
                                  {msg.record.result == null
                                    ? 'JSON output unavailable.'
                                    : JSON.stringify(msg.record.result, null, 2)}
                                </pre>
                              </div>
                            </div>
                          )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <div ref={chatBottomRef} />
            </div>
          )}
        </main>

        {/* Floating Gemini-Style Input Pill at Bottom when in chat */}
        {messages.length > 0 && <footer className="gemini-footer">{inputForm}</footer>}
      </div>

      {/* CSV Data Preview Modal */}
      {showCsvPreviewModal && dataset && (
        <div className="modal-backdrop" onClick={() => setShowCsvPreviewModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <FileSpreadsheet size={20} />
                <h3>{dataset.file.name} (Data Preview)</h3>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowCsvPreviewModal(false)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <p className="preview-note">
                Showing first {dataset.preview.length} rows out of {dataset.rowCount} rows.
              </p>
              <div className="table-wrapper">
                <table className="preview-table">
                  <thead>
                    <tr>
                      {dataset.headers.map((h, i) => (
                        <th key={i}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dataset.preview.map((row, rIndex) => (
                      <tr key={rIndex}>
                        {row.map((cell, cIndex) => (
                          <td key={cIndex}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
