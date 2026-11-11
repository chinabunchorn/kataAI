import { useEffect, useRef, useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Check,
  FileSpreadsheet,
  FileUp,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  X,
} from 'lucide-react'
import { inspectCsv } from './lib/csv'
import type { CsvDataset } from './lib/csv'
import { MAX_QUESTION_LENGTH, prepareSubmission, validateQuestion } from './lib/submission'
import type { PreparedSubmission } from './lib/submission'

const EXAMPLE_QUESTION =
  'Which product had the largest absolute drop in sales from October to November?'
const SAMPLE_CSV =
  'product,month,units\nNotebook,October,120\nNotebook,November,80\nPen,October,50\nPen,November,45\n'

export default function App() {
  const [question, setQuestion] = useState('')
  const [dataset, setDataset] = useState<CsvDataset | null>(null)
  const [questionError, setQuestionError] = useState<string>()
  const [fileError, setFileError] = useState<string>()
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [prepared, setPrepared] = useState<PreparedSubmission | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const questionInput = useRef<HTMLTextAreaElement>(null)
  const fileGeneration = useRef(0)
  const scrollFrame = useRef<number | null>(null)

  useEffect(() => {
    const cancelScroll = () => {
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current)
      scrollFrame.current = null
    }
    window.addEventListener('wheel', cancelScroll, { passive: true })
    window.addEventListener('touchstart', cancelScroll, { passive: true })
    window.addEventListener('keydown', cancelScroll)
    return () => {
      cancelScroll()
      window.removeEventListener('wheel', cancelScroll)
      window.removeEventListener('touchstart', cancelScroll)
      window.removeEventListener('keydown', cancelScroll)
    }
  }, [])

  function navigateSection(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      return
    const hash = event.currentTarget.hash
    const target = document.getElementById(hash.slice(1))
    if (!target) return
    event.preventDefault()
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current)
    const start = window.scrollY
    const headerHeight = document.querySelector('header')?.getBoundingClientRect().height ?? 0
    const end = Math.max(0, target.getBoundingClientRect().top + start - headerHeight)
    const finish = () => {
      scrollFrame.current = null
      history.replaceState(null, '', hash)
      target.focus({ preventScroll: true })
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo(0, end)
      finish()
      return
    }
    const started = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - started) / 1400, 1)
      const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
      window.scrollTo(0, start + (end - start) * eased)
      if (progress < 1) scrollFrame.current = requestAnimationFrame(tick)
      else finish()
    }
    scrollFrame.current = requestAnimationFrame(tick)
  }

  function resetDraft() {
    ++fileGeneration.current
    setQuestion('')
    setDataset(null)
    setPrepared(null)
    setQuestionError(undefined)
    setFileError(undefined)
    setReading(false)
    setDragging(false)
    if (input.current) input.current.value = ''
    questionInput.current?.focus()
  }

  async function selectFiles(files: File[]) {
    const generation = ++fileGeneration.current
    setPrepared(null)
    setDataset(null)
    setFileError(undefined)
    if (files.length !== 1) {
      setReading(false)
      setFileError('Choose one CSV at a time. Multiple files are not supported yet.')
      return
    }
    setReading(true)
    try {
      const inspected = await inspectCsv(files[0])
      if (generation === fileGeneration.current) setDataset(inspected)
    } catch (error) {
      if (generation === fileGeneration.current)
        setFileError(
          error instanceof Error
            ? error.message
            : 'This file could not be read. Please choose it again.',
        )
    } finally {
      if (generation === fileGeneration.current) setReading(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const error = validateQuestion(question)
    setQuestionError(error)
    if (!dataset)
      setFileError(
        reading
          ? 'Wait for your CSV to finish validating.'
          : 'Add a CSV file before checking your request.',
      )
    if (error) questionInput.current?.focus()
    else if (!dataset) input.current?.focus()
    if (error || !dataset || reading) return
    setPrepared(prepareSubmission(question, dataset))
  }

  return (
    <div className="site-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <header className="site-header">
        <a className="nav-brand" href="#top" onClick={navigateSection} aria-label="KataAI home">
          KataAI<span aria-hidden="true">·</span>
        </a>
        <span className="nav-caption"></span>
        <a href="#workspace" className="nav-cta" onClick={navigateSection}>
          <ArrowUpRight size={16} />
        </a>
      </header>
      <main>
        <section className="hero" id="top" tabIndex={-1} aria-labelledby="hero-title">
          <div className="hero-grid" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="hero-topline">
            <span>
              <i /> 
            </span>
            <span></span>
          </div>
          <div className="wordmark-stage">
            <div className="wordmark-overline"></div>
            <h1 id="hero-title" aria-label="KataAI">
              Kata<span>AI</span>
              <span className="wordmark-period" aria-hidden="true">
                
              </span>
            </h1>
            <span className="wordmark-index" aria-hidden="true">
              
            </span>
          </div>
          <div className="hero-bottom">
            <div className="hero-statement">
              <h2>
                
              </h2>
              <p>
                 
                
              </p>
            </div>
            <div className="hero-action">
              <a href="#workspace" className="hero-cta" onClick={navigateSection}>
                Start exploring{' '}
                <span>
                  <ArrowDown size={20} />
                </span>
              </a>
              <p>
                One question. One dataset.
                <br />A simple place to begin.
              </p>
            </div>
          </div>
          <div className="hero-baseline">
            <span>DESIGNED FOR EXPLORATION</span>
            <a href="#workspace" onClick={navigateSection}>
              Scroll to begin <span className="scroll-line" />
              <ArrowDown size={14} />
            </a>
            <span>INTERACTIVE FRONTEND PREVIEW</span>
          </div>
        </section>

        <section
          className="workspace"
          id="workspace"
          tabIndex={-1}
          aria-labelledby="workspace-title"
        >
          <div className="section-topline">
            <span>02 / YOUR STARTING POINT</span>
            <span className="local-badge">
              <span /> Local preview
            </span>
          </div>
          <div className="workspace-intro">
            <h2 id="workspace-title">
              Less busywork.
              <br />
              <span>More “what if?”</span>
            </h2>
            <div>
              <p>
                A question worth asking.
                <br />A dataset worth exploring.
              </p>
              <span>
                Write what's on your mind and bring a CSV. <br />
                We'll check that your request is ready.
              </span>
            </div>
          </div>
          <div className="workbench">
            <div className="workbench-toolbar">
              <span>LET'S MAKE A START</span>
              <button className="reset-button" type="button" onClick={resetDraft}>
                <RotateCcw size={14} /> Reset draft
              </button>
            </div>
            <form onSubmit={submit} noValidate>
              <div className="input-grid">
                <div className="question-section">
                  <div className="field-heading">
                    <label htmlFor="question">Your question</label>
                    <span>01</span>
                  </div>
                  <p id="question-help" className="field-description">
                    What would you like to find out?
                  </p>
                  <div className={`textarea-wrap ${questionError ? 'invalid' : ''}`}>
                    <textarea
                      ref={questionInput}
                      id="question"
                      name="question"
                      aria-label="Your question"
                      aria-required="true"
                      value={question}
                      aria-describedby={`question-help question-count${questionError ? ' question-error' : ''}`}
                      aria-invalid={!!questionError}
                      placeholder="Which product had the biggest drop in sales last month?"
                      onChange={(event) => {
                        setQuestion(event.target.value)
                        setQuestionError(undefined)
                        setPrepared(null)
                      }}
                    />
                    <div className="textarea-footer">
                      <span>Ask in your own words.</span>
                      <span
                        id="question-count"
                        className={question.length > MAX_QUESTION_LENGTH ? 'over-limit' : ''}
                      >
                        {question.length.toLocaleString('en-US')} / 4,000
                      </span>
                    </div>
                  </div>
                  {questionError && (
                    <p id="question-error" className="field-error" role="alert">
                      {questionError}
                    </p>
                  )}
                  <button
                    type="button"
                    className="text-button example-question"
                    onClick={() => {
                      setQuestion(EXAMPLE_QUESTION)
                      setQuestionError(undefined)
                      setPrepared(null)
                      questionInput.current?.focus()
                    }}
                  >
                    Try an example question <ArrowUpRight size={14} />
                  </button>
                </div>
                <div className="dataset-section">
                  <div className="field-heading">
                    <label htmlFor="csv-file">Your dataset</label>
                    <span>02</span>
                  </div>
                  <p id="file-help" className="field-description">
                    One UTF-8 CSV. Up to 128 KiB.
                  </p>
                  <div
                    className={`dropzone ${dragging ? 'dragging' : ''} ${fileError ? 'invalid' : ''} ${dataset ? 'has-file' : ''}`}
                    onDragOver={(event) => {
                      event.preventDefault()
                      setDragging(true)
                    }}
                    onDragLeave={(event) => {
                      if (
                        !(event.relatedTarget instanceof Node) ||
                        !event.currentTarget.contains(event.relatedTarget)
                      )
                        setDragging(false)
                    }}
                    onDrop={(event) => {
                      event.preventDefault()
                      setDragging(false)
                      void selectFiles(Array.from(event.dataTransfer.files))
                      if (input.current) input.current.value = ''
                    }}
                  >
                    <input
                      ref={input}
                      className="file-input"
                      type="file"
                      id="csv-file"
                      aria-label="Choose CSV file"
                      aria-required="true"
                      accept=".csv,text/csv"
                      aria-describedby={`file-help${fileError ? ' file-error' : ''}`}
                      aria-invalid={!!fileError}
                      onChange={(event) => {
                        if (event.target.files?.length)
                          void selectFiles(Array.from(event.target.files))
                        event.target.value = ''
                      }}
                    />
                    {reading ? (
                      <div className="drop-empty" role="status">
                        <LoaderCircle className="spin" size={30} />
                        <strong>Checking your CSV…</strong>
                        <span>Everything stays in this browser.</span>
                      </div>
                    ) : dataset ? (
                      <div className="selected-file">
                        <span className="file-icon">
                          <FileSpreadsheet size={31} strokeWidth={1.3} />
                        </span>
                        <strong>{dataset.file.name}</strong>
                        <span className="file-info">
                          {dataset.rowCount.toLocaleString('en-US')} rows · {dataset.headers.length}{' '}
                          columns · {(dataset.file.size / 1024).toFixed(1)} KiB
                        </span>
                        <span className="valid-file">
                          <Check size={13} /> CSV structure checked
                        </span>
                        <button
                          type="button"
                          className="icon-button remove-file"
                          aria-label="Remove file"
                          onClick={() => {
                            ++fileGeneration.current
                            setDataset(null)
                            setPrepared(null)
                            setFileError(undefined)
                          }}
                        >
                          <X size={18} />
                        </button>
                      </div>
                    ) : (
                      <div className="drop-empty">
                        <span className="upload-mark">
                          <FileUp size={34} strokeWidth={1.25} />
                        </span>
                        <strong>A home for your data.</strong>
                        <span>
                          Drop your CSV here, or{' '}
                          <button
                            type="button"
                            className="inline-button"
                            onClick={() => input.current?.click()}
                          >
                            browse files
                          </button>
                          .
                        </span>
                        <span className="file-limit">.CSV / MAX 128 KiB</span>
                      </div>
                    )}
                  </div>
                  {fileError && (
                    <p className="field-error" id="file-error" role="alert">
                      {fileError}
                    </p>
                  )}
                  <button
                    type="button"
                    className="text-button sample-button"
                    onClick={() => {
                      void selectFiles([
                        new File([SAMPLE_CSV], 'sample-sales.csv', { type: 'text/csv' }),
                      ])
                    }}
                  >
                    Use sample CSV <ArrowUpRight size={14} />
                  </button>
                </div>
              </div>
              {dataset && (
                <details className="csv-preview">
                  <summary>
                    Preview dataset <span>First {Math.min(dataset.rowCount, 5)} rows</span>
                  </summary>
                  <div className="table-scroll" tabIndex={0} role="region" aria-label="CSV preview">
                    <table>
                      <thead>
                        <tr>
                          {dataset.headers.map((header, index) => (
                            <th key={index} scope="col">
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dataset.preview.map((row, index) => (
                          <tr key={index}>
                            {row.map((cell, cellIndex) => (
                              <td key={cellIndex}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p>Just a preview. Your original file is unchanged.</p>
                </details>
              )}
              <div className="submit-row">
                <div>
                  <LockKeyhole size={17} />
                  <p>
                    Your data stays with you.
                    <span>Local validation only. Nothing is uploaded.</span>
                  </p>
                </div>
                <button type="submit" className="primary-button" disabled={reading}>
                  Check my request <ArrowRight size={18} />
                </button>
              </div>
            </form>
            {prepared && (
              <div className="request-confirmation" role="status">
                <span>
                  <Check size={20} />
                </span>
                <div>
                  <h3>Your request is ready.</h3>
                  <p>Nothing has been sent. Backend integration is not connected yet.</p>
                </div>
              </div>
            )}
          </div>
          <div className="workspace-footnote">
            <span>BIG IDEAS START SMALL.</span>
            <span>No uploads. No model calls. No code execution.</span>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <div className="footer-top">
          <a href="#top" className="footer-brand" onClick={navigateSection}>
            KataAI<span>.</span>
          </a>
          <p>
            Stay curious.
            <br />
            There's more to ask.
          </p>
          <a href="#top" className="back-top" onClick={navigateSection} aria-label="Back to top">
            <ArrowUp size={20} />
          </a>
        </div>
        <div className="footer-bottom">
          <span>A SANDBOXED ANALYSIS PROJECT</span>
          <span>Built around a better question.</span>
          <a href="#workspace" onClick={navigateSection}>
            Try it for yourself <ArrowUpRight size={13} />
          </a>
        </div>
      </footer>
    </div>
  )
}
