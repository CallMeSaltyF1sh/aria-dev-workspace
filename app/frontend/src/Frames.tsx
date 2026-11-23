import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, time, type Asset, type Group, type Job } from './api'
import styles from './Detail.module.css'

export function Frames({ asset }: { asset: Asset }) {
  const client = useQueryClient()
  const [target, setTarget] = useState('0')
  const [count, setCount] = useState('5')
  const [spacing, setSpacing] = useState('0.4')
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const groups = useQuery({
    queryKey: ['frames', asset.id],
    queryFn: () => api<Group[]>('/assets/' + asset.id + '/frames'),
  })
  const history = useQuery({
    queryKey: ['jobs', asset.id],
    queryFn: () => api<Job[]>('/assets/' + asset.id + '/jobs'),
  })
  const latest = jobId || history.data?.find((j) => j.kind === 'frames')?.id
  const job = useQuery({
    queryKey: ['job', latest],
    enabled: !!latest,
    queryFn: () => api<Job>('/jobs/' + latest),
    refetchInterval: (query) =>
      ['queued', 'running'].includes(query.state.data?.status || 'queued')
        ? 600
        : false,
  })
  useEffect(() => {
    if (job.data?.status === 'completed')
      void client.invalidateQueries({ queryKey: ['frames', asset.id] })
  }, [job.data?.status, client, asset.id])
  const processing =
    busy || ['queued', 'running'].includes(job.data?.status || '')
  return (
    <div className="stack">
      <section className="card">
        <div className="cardHead">
          <h2>Generate frames</h2>
        </div>
        <form
          className="cardBody"
          onSubmit={(e) => {
            e.preventDefault()
            setBusy(true)
            setError('')
            void api<Job>('/assets/' + asset.id + '/frames', 'POST', {
              target_ms: Math.round(Number(target) * 1000),
              count: Number(count),
              spacing_ms: Math.round(Number(spacing) * 1000),
              width: 1280,
            })
              .then((value) => setJobId(value.id))
              .catch((error) => setError(error.message))
              .finally(() => setBusy(false))
          }}
        >
          <div className={styles.fields}>
            <label>
              Target time (s)
              <input
                required
                type="number"
                min="0"
                max={(asset.info.duration_ms || 1) / 1000 - 0.001}
                step="0.1"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </label>
            <label>
              Frames per group
              <input
                type="number"
                required
                min="1"
                max="31"
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
            </label>
            <label>
              Frame spacing (s)
              <input
                type="number"
                required
                min="0.1"
                max="60"
                step="0.1"
                value={spacing}
                onChange={(e) => setSpacing(e.target.value)}
              />
            </label>
          </div>
          <div className="actions">
            <button
              className="primary"
              disabled={
                processing || !!asset.missing || asset.info.status === 'error'
              }
            >
              {processing ? 'Generating…' : 'Generate frames'}
            </button>
            <span className="small muted">
              {job.data?.status === 'completed'
                ? 'Ready on disk'
                : processing
                  ? 'Preparing local frame group…'
                  : ''}
            </span>
          </div>
          {(error || job.data?.error) && (
            <p className="error" role="alert">
              {error || job.data?.error}
            </p>
          )}
        </form>
      </section>
      {groups.isPending ? (
        <p>Loading frame groups…</p>
      ) : groups.isError ? (
        <p className="error">{groups.error.message}</p>
      ) : !groups.data.length ? (
        <div className="card empty">
          No frames generated. Choose a target and generate a frame group.
        </div>
      ) : (
        groups.data.map((group) => (
          <section className="card" key={group.id}>
            <div className="cardHead">
              <div>
                <h2>Target {time(group.settings.target_ms)}</h2>
                <span className="small muted mono">
                  workspace/frames/{asset.id}/{group.id}/
                </span>
              </div>
              <span className="badge">
                {group.source_changed
                  ? 'Source changed'
                  : group.frames.length + ' frames'}
              </span>
            </div>
            <div className={styles.frameGrid}>
              {group.frames.map((frame) => (
                <figure
                  key={frame.file}
                  className={frame.is_target ? styles.targetFrame : ''}
                >
                  <img
                    src={
                      '/api/assets/' +
                      asset.id +
                      '/frames/' +
                      group.id +
                      '/' +
                      frame.file
                    }
                    alt={'Video frame ' + time(frame.actual_ms)}
                    loading="lazy"
                  />
                  <figcaption>
                    <b>{frame.is_target ? 'Target' : 'Context'}</b>
                    <span>Requested {time(frame.requested_ms, 3)}</span>
                    <span>Actual {time(frame.actual_ms, 3)}</span>
                    <span>
                      Δ {(frame.actual_ms - frame.requested_ms).toFixed(1)} ms
                    </span>
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  )
}
