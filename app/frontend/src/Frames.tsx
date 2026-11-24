import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  time,
  type Asset,
  type Group,
  type Job,
  type FramePage,
} from './api'
import styles from './Detail.module.css'

export function Frames({ asset }: { asset: Asset }) {
  const client = useQueryClient()
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
  const latest =
    jobId ||
    history.data?.find(
      (j) => j.kind === 'frames' && j.key.includes('"interval_ms"'),
    )?.id
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
  }, [job.data?.id, job.data?.status, client, asset.id])
  const processing =
    busy ||
    (!!latest && job.isPending) ||
    ['queued', 'running'].includes(job.data?.status || '')
  const sets = groups.data?.filter((group) => group.mode === 'full_video') || []
  const completed = Number(job.data?.progress?.completed || 0)
  const total = Number(job.data?.progress?.total || 0)
  const stage = String(job.data?.progress?.stage || '')
  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      const value = await api<Job>('/assets/' + asset.id + '/frames', 'POST', {
        interval_ms: 100,
        width: 1280,
      })
      setJobId(value.id)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack">
      <section className="card">
        <div className="cardHead">
          <h2>Generate frames</h2>
          <span className="badge">Entire recording · 0.1 s</span>
        </div>
        <div className="cardBody">
          <div className="actions">
            <button
              className="primary"
              disabled={
                processing || !!asset.missing || asset.info.status === 'error'
              }
              onClick={generate}
            >
              {processing ? 'Generating…' : 'Generate frames'}
            </button>
            <span className="small muted" role="status">
              {processing
                ? stage === 'validating'
                  ? 'Checking source…'
                  : total
                    ? `${completed} / ${total} frames`
                    : 'Reading timestamps…'
                : job.data?.status === 'completed' && sets.length
                  ? 'Ready on disk'
                  : ''}
            </span>
          </div>
          {processing && (
            <progress
              className={styles.generationProgress}
              aria-label="Frame generation"
              max={total || 1}
              value={total ? completed : undefined}
            />
          )}
          {(error || job.data?.error) && (
            <p className="error" role="alert">
              {error || job.data?.error}
            </p>
          )}
          {history.isError && (
            <p className="error" role="alert">
              {history.error.message}
            </p>
          )}
        </div>
      </section>
      {groups.isPending ? (
        <p>Loading frame sets…</p>
      ) : groups.isError ? (
        <p className="error">{groups.error.message}</p>
      ) : !sets.length ? (
        <div className="card empty">No full-video frames generated.</div>
      ) : (
        sets.map((group) => (
          <FrameSet key={group.id} group={group} assetId={asset.id} />
        ))
      )}
    </div>
  )
}

function FrameSet({ group, assetId }: { group: Group; assetId: string }) {
  const [page, setPage] = useState(1)
  const frames = useQuery({
    queryKey: ['frame-page', assetId, group.id, page],
    queryFn: () =>
      api<FramePage>(
        `/assets/${assetId}/frames/${group.id}?page=${page}&page_size=24`,
      ),
  })
  const pages = Math.max(1, Math.ceil(group.frame_count / 24))
  return (
    <section className={`card ${styles.frameSet}`}>
      <div className="cardHead">
        <div>
          <h2>{group.frame_count} frames</h2>
          <span className="small muted mono">
            workspace/frames/{assetId}/{group.id}/
          </span>
        </div>
        <span className="badge">
          {group.source_changed
            ? 'Source changed'
            : group.sample_count + ' sample times'}
        </span>
      </div>
      {frames.isPending ? (
        <p className="empty">Loading frames…</p>
      ) : frames.isError ? (
        <p className="error cardBody">{frames.error.message}</p>
      ) : (
        <div className={styles.frameGrid}>
          {frames.data.frames.map((frame) => (
            <figure key={frame.file}>
              <img
                src={`/api/assets/${assetId}/frames/${group.id}/${frame.file}`}
                alt={'Video frame ' + time(frame.actual_ms, 3)}
                loading="lazy"
              />
              <figcaption>
                <b>{time(frame.actual_ms, 3)}</b>
                <span>Requested {time(frame.requested_ms, 3)}</span>
                <span>
                  Δ{' '}
                  {Number(
                    (frame.actual_ms - frame.requested_ms).toFixed(1),
                  ).toFixed(1)}{' '}
                  ms
                </span>
                {frame.requested_times_ms &&
                  frame.requested_times_ms.length > 1 && (
                    <span>
                      {frame.requested_times_ms.length} sample times · 1 source
                      frame
                    </span>
                  )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      <div className={`cardBody actions spread ${styles.pagination}`}>
        <span className="small muted">
          Page {page} of {pages} · 24 per page
        </span>
        <div className="actions">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            Previous page
          </button>
          <button
            disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next page
          </button>
        </div>
      </div>
    </section>
  )
}
