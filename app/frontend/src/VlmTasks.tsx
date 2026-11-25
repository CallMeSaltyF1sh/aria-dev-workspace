import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type VlmRunListItem } from './api'

const setup = (run: VlmRunListItem) =>
  `${String(run.settings.model)} · step ${Number(run.settings.step_ms) / 1000}s · ±${Number(run.settings.context_ms) / 1000}s`
const answers = ({ counts }: VlmRunListItem) => {
  const total = counts.valid + counts.invalid_output + counts.request_failed
  const problems = [
    counts.request_failed && `${counts.request_failed} failed`,
    counts.invalid_output && `${counts.invalid_output} invalid`,
  ].filter(Boolean)
  return `${counts.valid}/${total} answered${problems.length ? ' · ' + problems.join(' · ') : ''}`
}
const runLink = (run: VlmRunListItem) =>
  `/data/${run.asset_id}?tab=tasks&run=${encodeURIComponent(run.id)}`

export function TasksPage() {
  const navigate = useNavigate()
  const runs = useQuery({
    queryKey: ['vlm-all-runs'],
    queryFn: () => api<VlmRunListItem[]>('/vlm/runs'),
    staleTime: 0,
  })
  const [prompt, setPrompt] = useState('')
  if (runs.isPending) return <p>Loading runs…</p>
  if (runs.isError) return <p className="error">{runs.error.message}</p>
  const prompts = [...new Set(runs.data.map((r) => r.prompt_id))].sort(
    (a, b) => Number(b.slice(1)) - Number(a.slice(1)),
  )
  const shown = runs.data.filter((r) => !prompt || r.prompt_id === prompt)
  return (
    <>
      <h1>VLM Tasks</h1>
      <p className="small muted">
        Every VLM run across recordings. Click a run to open it in its
        recording&apos;s VLM Run tab. Start a run from that tab; running several
        recordings at once is planned. Comparing results with annotations
        belongs to Evaluation.
      </p>
      {!runs.data.length ? (
        <div className="card empty">
          No VLM runs yet. Open a recording in Data Library and use its VLM Run
          tab.
        </div>
      ) : (
        <section className="card">
          <div className="cardHead">
            <h2>Runs</h2>
            <label className="check" style={{ marginBottom: 0 }}>
              Prompt
              <select
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              >
                <option value="">All versions</option>
                {prompts.map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="tableScroll">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Recording</th>
                  <th>Prompt</th>
                  <th>Model and setup</th>
                  <th>Answers</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((run) => (
                  <tr
                    key={run.asset_id + run.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(runLink(run))}
                  >
                    <td className="small">
                      <Link to={runLink(run)}>
                        {new Date(run.created_at).toLocaleString()}
                      </Link>
                    </td>
                    <td className="mono small">{run.video_id}</td>
                    <td className="mono">{run.prompt_id}</td>
                    <td className="small">{setup(run)}</td>
                    <td className="small">{answers(run)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
