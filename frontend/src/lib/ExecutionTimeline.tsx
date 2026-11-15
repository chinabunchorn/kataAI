import type { ExecutionStage } from './api'
export const stageLabel = (name: string) =>
  ({
    queued: 'Queue wait',
    checking_execution: 'Checking execution status (uncertain)',
    preparing_input: 'Preparing dataset',
    generating_code: 'LLM processing',
    validating_code: 'Validating generated code',
    starting_execution: 'Starting Kata execution',
    waiting_for_container: 'Starting Kata container / VM',
    running_in_kata: 'Running in Kata container',
    collecting_result: 'Collecting Python result',
    summarizing: 'LLM summarizing',
  })[name] ?? name
export function formatLatency(ms: number) {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`
}
export default function ExecutionTimeline({ stages }: { stages?: ExecutionStage[] }) {
  if (!stages?.length) return null
  return (
    <section className="execution-timeline" aria-label="Execution stages">
      <ol>
        {stages.map((stage) => (
          <li key={stage.name} className={stage.finished_at ? 'ended' : 'active'}>
            <span>
              {stageLabel(stage.name)}
              {!stage.finished_at && <span className="stage-active"> · active</span>}
            </span>
            <span className="stage-duration">
              {formatLatency(stage.duration_ms ?? stage.elapsed_ms)}
              {!stage.finished_at && ' so far'}
              {stage.outcome &&
                stage.outcome !== 'finished' &&
                stage.outcome !== 'completed' &&
                ` · ${stage.outcome}`}
            </span>
          </li>
        ))}
      </ol>
      <p>
        Backend-observed timings. VM startup and execution are observed through Kubernetes Pod
        state; short stages may finish between polls. Active time is as of the latest update.
      </p>
    </section>
  )
}
