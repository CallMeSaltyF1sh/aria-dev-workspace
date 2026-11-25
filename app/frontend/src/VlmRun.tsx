import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  time,
  type Asset,
  type Draft,
  type Job,
  type Library,
  type PromptSummary,
  type VlmConfig,
  type VlmRun,
  type VlmRunSummary,
  type VlmSettings,
} from './api'
import styles from './Detail.module.css'

export function VlmPanel({
  asset,
  draft,
  phases,
}: {
  asset: Asset
  draft: Draft
  phases: Library['phases']
}) {
  const client = useQueryClient()
  const config = useQuery({
    queryKey: ['vlm-config'],
    queryFn: () => api<VlmConfig>('/vlm/config'),
  })
  const promptList = useQuery({
    queryKey: ['prompts'],
    queryFn: () => api<PromptSummary[]>('/prompts'),
  })
  const [settings, setSettings] = useState<VlmSettings>({
    model: '',
    garment: (asset.study.garment as VlmSettings['garment']) || '',
    step_ms: 500,
    context_ms: 2000,
    width: 640,
    workers: 8,
    prompt_id: null,
  })
  const [jobId, setJobId] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState('')
  const runs = useQuery({
    queryKey: ['vlm-runs', asset.id],
    queryFn: () => api<VlmRunSummary[]>('/assets/' + asset.id + '/vlm'),
  })
  const history = useQuery({
    queryKey: ['jobs', asset.id],
    queryFn: () => api<Job[]>('/assets/' + asset.id + '/jobs'),
  })
  const latest = jobId || history.data?.find((j) => j.kind === 'vlm')?.id
  const job = useQuery({
    queryKey: ['job', latest],
    enabled: !!latest,
    queryFn: () => api<Job>('/jobs/' + latest),
    refetchInterval: (q) =>
      ['queued', 'running'].includes(q.state.data?.status || 'queued')
        ? 1000
        : false,
  })
  useEffect(() => {
    if (job.data?.status === 'completed') {
      void client.invalidateQueries({ queryKey: ['vlm-runs', asset.id] })
      setSelected(String(job.data.result?.id))
    }
  }, [job.data?.status, job.data?.result?.id, client, asset.id])
  const running = ['queued', 'running'].includes(job.data?.status || '')
  const runId = selected || runs.data?.[0]?.id
  const progress = job.data?.progress
  // Until a model is picked, use the first one listed in VLM_MODELS.
  const model = settings.model || config.data?.models[0] || ''
  const set = <K extends keyof VlmSettings>(key: K, value: VlmSettings[K]) =>
    setSettings({ ...settings, [key]: value })
  const start = () => {
    setError('')
    api<Job>('/assets/' + asset.id + '/vlm', 'POST', { ...settings, model })
      .then((j) => setJobId(j.id))
      .catch((e) => setError(e.message))
  }
  return (
    <div className="stack">
      <section className="card">
        <div className="cardHead">
          <h2>Run VLM</h2>
          <span className="badge">
            {config.data?.configured
              ? 'API key configured'
              : 'AIHUBMIX_API_KEY missing in .env.local'}
          </span>
        </div>
        <div className="cardBody">
          <p className="small muted">
            One request per target point, with context frames on both sides,
            taken from the 0.1 s frame cache (generated automatically if
            missing). Each request sends{' '}
            {1 + 2 * Math.floor(settings.context_ms / settings.step_ms)} frames;
            about {Math.ceil((asset.info.duration_ms || 0) / settings.step_ms)}{' '}
            requests for this recording.
          </p>
          <div className={styles.fields}>
            <label>
              Model
              <select
                value={model}
                onChange={(e) => set('model', e.target.value)}
              >
                {(config.data?.models || []).map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>
              Prompt
              <select
                value={settings.prompt_id || ''}
                onChange={(e) => set('prompt_id', e.target.value || null)}
              >
                <option value="">
                  Newest
                  {promptList.data?.[0] ? ` (${promptList.data[0].id})` : ''}
                </option>
                {promptList.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id} · {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Garment
              <select
                value={settings.garment}
                onChange={(e) =>
                  set('garment', e.target.value as VlmSettings['garment'])
                }
              >
                <option value="">Choose</option>
                <option>shirt</option>
                <option>jacket</option>
              </select>
            </label>
            <label>
              Step (label resolution)
              <select
                value={settings.step_ms}
                onChange={(e) =>
                  set(
                    'step_ms',
                    Number(e.target.value) as VlmSettings['step_ms'],
                  )
                }
              >
                {[500, 1000, 2000].map((v) => (
                  <option key={v} value={v}>
                    {v / 1000} s
                  </option>
                ))}
              </select>
            </label>
            <label>
              Context each side
              <select
                value={settings.context_ms}
                onChange={(e) =>
                  set(
                    'context_ms',
                    Number(e.target.value) as VlmSettings['context_ms'],
                  )
                }
              >
                {[0, 1000, 2000, 4000].map((v) => (
                  <option key={v} value={v}>
                    {v / 1000} s
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="actions">
            <button
              className="primary"
              disabled={
                running ||
                !config.data?.configured ||
                !settings.garment ||
                !!asset.missing
              }
              onClick={start}
            >
              {running ? 'Running…' : 'Run VLM'}
            </button>
            <span className="small muted" role="status">
              {running &&
                (progress?.stage === 'requesting'
                  ? `${progress.completed} / ${progress.total} requests`
                  : 'Preparing frames…')}
            </span>
          </div>
          {running && (
            <progress
              className={styles.generationProgress}
              max={Number(progress?.total) || 1}
              value={
                progress?.stage === 'requesting'
                  ? Number(progress.completed)
                  : undefined
              }
            />
          )}
          {(error || job.data?.status === 'failed') && (
            <p className="error" role="alert">
              {error || job.data?.error}
            </p>
          )}
        </div>
      </section>
      {runs.data && !runs.data.length ? (
        <div className="card empty">No VLM runs for this recording yet.</div>
      ) : (
        runs.data && (
          <section className="card">
            <div className="cardHead">
              <h2>Results</h2>
              <select
                aria-label="VLM run"
                value={runId}
                onChange={(e) => setSelected(e.target.value)}
              >
                {runs.data.map((r) => (
                  <option key={r.id} value={r.id}>
                    {new Date(r.created_at).toLocaleString()} ·{' '}
                    {String(r.settings.model)} ·{' '}
                    {String(r.settings.prompt_id ?? 'v1')} · {r.counts.valid}{' '}
                    valid
                  </option>
                ))}
              </select>
            </div>
            {runId && (
              <RunResult
                assetId={asset.id}
                runId={runId}
                draft={draft}
                phases={phases}
              />
            )}
          </section>
        )
      )}
    </div>
  )
}

function RunResult({
  assetId,
  runId,
  draft,
  phases,
}: {
  assetId: string
  runId: string
  draft: Draft
  phases: Library['phases']
}) {
  const run = useQuery({
    queryKey: ['vlm-run', assetId, runId],
    queryFn: () => api<VlmRun>(`/assets/${assetId}/vlm/${runId}`),
  })
  if (run.isPending) return <p className="empty">Loading run…</p>
  if (run.isError) return <p className="error cardBody">{run.error.message}</p>
  const value = run.data
  const total = draft.duration_ms || 1
  const human = (ms: number) =>
    draft.intervals.find((i) => ms >= i.start_ms && ms < i.end_ms)?.phase ??
    null
  const scored = value.windows.filter(
    (w) => w.status === 'valid' && human(w.target_ms),
  )
  const agree = scored.filter((w) => w.label === human(w.target_ms)).length
  const color = (label: string | null) =>
    (label && phases[label as keyof typeof phases]?.color) || '#fff'
  const track = (
    items: { start_ms: number; end_ms: number; label: string | null }[],
  ) => (
    <div className={styles.vlmTrack}>
      {items.map((s, i) => (
        <span
          key={i}
          title={`${s.label ?? 'unlabeled'} ${time(s.start_ms)}–${time(s.end_ms)}`}
          style={{
            left: (s.start_ms / total) * 100 + '%',
            width: ((s.end_ms - s.start_ms) / total) * 100 + '%',
            background: color(s.label),
          }}
        >
          {s.label}
        </span>
      ))}
    </div>
  )
  return (
    <div className="cardBody stack">
      <p className="small muted">
        {value.counts.valid} valid · {value.counts.invalid_output} invalid
        output · {value.counts.request_failed} failed · {value.seconds}s ·
        garment {String(value.settings.garment)} · step{' '}
        {Number(value.settings.step_ms) / 1000}s · context ±
        {Number(value.settings.context_ms) / 1000}s{' · prompt '}
        {value.prompt_id ?? 'v1'} ({value.prompt_hash})
        {scored.length > 0 &&
          ` · agrees with saved annotation on ${agree}/${scored.length} target points (${Math.round((agree / scored.length) * 100)}%)`}
      </p>
      <div>
        <span className="small muted">Human annotation</span>
        {track(
          draft.intervals.map((i) => ({
            start_ms: i.start_ms,
            end_ms: i.end_ms,
            label: i.phase ?? null,
          })),
        )}
        <span className="small muted">
          Model ({String(value.settings.model)})
        </span>
        {track(value.phases)}
      </div>
      <div className="tableScroll">
        <table>
          <thead>
            <tr>
              <th>Target</th>
              <th>Human</th>
              <th>Model</th>
              <th>Reason / error</th>
            </tr>
          </thead>
          <tbody>
            {value.windows.map((w) => (
              <tr key={w.start_ms}>
                <td className="mono">{time(w.actual_target_ms, 2)}</td>
                <td>{human(w.target_ms) ?? '—'}</td>
                <td>{w.label}</td>
                <td className="small">{w.reason || w.error}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
