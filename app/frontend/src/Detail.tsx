import { useCallback, useEffect, useRef, useState } from 'react'
import {
  useBlocker,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconArrowLeft,
  IconArrowRight,
  IconPlayerPlay,
  IconPlus,
} from '@tabler/icons-react'
import {
  api,
  time,
  type Asset,
  type Draft,
  type Job,
  type Library,
  type Study,
} from './api'
import { Annotation } from './Annotation'
import { Frames } from './Frames'
import { filterAssets } from './libraryFilters'
import { Modal } from './components'
import styles from './Detail.module.css'

export function DetailPage({
  assetId,
  library,
}: {
  assetId: string
  library: Library
}) {
  const location = useLocation(),
    navigate = useNavigate(),
    client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'video'
  const state = location.state as { order?: string[]; returnTo?: string } | null
  const order =
    state?.order || filterAssets(library.assets, params).map((a) => a.id)
  const index = order.indexOf(assetId)
  const listParams = new URLSearchParams(params)
  listParams.delete('tab')
  const returnTo = state?.returnTo || '/data?' + listParams.toString()
  const [dirty, setDirty] = useState(false)
  const [current, setCurrent] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [mediaError, setMediaError] = useState(false)
  const [proxyJob, setProxyJob] = useState<string | null>(null)
  const [error, setError] = useState('')
  const video = useRef<HTMLVideoElement>(null)
  const save = useRef<() => Promise<boolean>>(async () => true)
  const addSplit = useRef<() => void>(() => {})
  const registerAdd = useCallback((callback: () => void) => {
    addSplit.current = callback
  }, [])
  const registerSave = useCallback((callback: () => Promise<boolean>) => {
    save.current = callback
  }, [])
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])
  const asset = useQuery({
    queryKey: ['asset', assetId],
    queryFn: () => api<Asset>('/assets/' + assetId),
  })
  const annotation = useQuery({
    queryKey: ['annotation', assetId],
    queryFn: () => api<Draft>('/assets/' + assetId + '/annotation'),
  })
  const times = useQuery({
    queryKey: ['timestamps', assetId],
    enabled:
      !!asset.data && !asset.data.missing && asset.data.info.status !== 'error',
    queryFn: () => api<number[]>('/assets/' + assetId + '/timestamps'),
  })
  const history = useQuery({
    queryKey: ['jobs', assetId],
    queryFn: () => api<Job[]>('/assets/' + assetId + '/jobs'),
  })
  const latest = proxyJob || history.data?.find((j) => j.kind === 'preview')?.id
  const job = useQuery({
    queryKey: ['job', latest],
    enabled: !!latest,
    queryFn: () => api<Job>('/jobs/' + latest),
    refetchInterval: (q) =>
      ['queued', 'running'].includes(q.state.data?.status || 'queued')
        ? 800
        : false,
  })
  useEffect(() => {
    if (job.data?.status === 'completed') {
      setMediaError(false)
      video.current?.load()
    }
  }, [job.data?.status])
  useEffect(() => {
    if (tab !== 'video') video.current?.pause()
  }, [tab])
  if (asset.isPending || annotation.isPending) return <p>Opening recording…</p>
  if (asset.isError || annotation.isError)
    return (
      <p className="error">
        {asset.error?.message || annotation.error?.message}
      </p>
    )
  const item = asset.data!,
    draft = annotation.data!
  const seek = (ms: number) => {
    if (video.current)
      video.current.currentTime = Math.max(
        0,
        Math.min((item.info.duration_ms || 0) / 1000, ms / 1000),
      )
  }
  const step = (direction: number) => {
    const timestamps = times.data
    if (!timestamps) return
    const position = (video.current?.currentTime || 0) * 1000
    let nearest = 0
    timestamps.forEach((t, i) => {
      if (Math.abs(t - position) < Math.abs(timestamps[nearest] - position))
        nearest = i
    })
    seek(
      timestamps[
        Math.max(0, Math.min(timestamps.length - 1, nearest + direction))
      ],
    )
  }
  const go = (id: string) =>
    navigate('/data/' + id + '?' + params.toString(), {
      state: { order, returnTo },
    })
  return (
    <>
      <h1>Video detail</h1>
      <div className="pageHead">
        <button className="textButton" onClick={() => navigate(returnTo)}>
          <IconArrowLeft size={16} />
          Back to Data Library
        </button>
        <div className="actions">
          <button disabled={index <= 0} onClick={() => go(order[index - 1])}>
            <IconArrowLeft size={16} />
            Previous item
          </button>
          <button
            disabled={index < 0 || index === order.length - 1}
            onClick={() => go(order[index + 1])}
          >
            Next item
            <IconArrowRight size={16} />
          </button>
        </div>
      </div>
      <p className="muted small mono">{item.path}</p>
      <div className={styles.tabs} role="tablist" aria-label="Recording detail">
        {[
          ['video', 'Video & Annotation'],
          ['metadata', 'Metadata'],
          ['frames', 'Frames & QC'],
          ['tasks', 'Related Tasks'],
        ].map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            key={key}
            onClick={() =>
              setParams(
                (p) => {
                  p.set('tab', key)
                  return p
                },
                { state: location.state },
              )
            }
          >
            {label}
          </button>
        ))}
      </div>
      <div hidden={tab !== 'video'} className="stack">
        <section className="card">
          <video
            className={styles.video}
            ref={video}
            src={
              (!item.missing && item.path.endsWith('.mp4')) ||
              job.data?.status === 'completed'
                ? '/api/assets/' + assetId + '/media'
                : undefined
            }
            onError={() => setMediaError(true)}
            onTimeUpdate={() =>
              setCurrent((video.current?.currentTime || 0) * 1000)
            }
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            preload="metadata"
            playsInline
          />
          {(mediaError || item.path.endsWith('.vrs')) && (
            <div className="cardBody">
              <p>
                {item.info.error ||
                  'Prepare a browser-compatible preview if this recording cannot play.'}
              </p>
              <button
                disabled={
                  !!item.missing ||
                  ['running', 'queued'].includes(job.data?.status || '')
                }
                onClick={() => {
                  void api<Job>('/assets/' + assetId + '/preview', 'POST')
                    .then((j) => setProxyJob(j.id))
                    .catch((e) => setError(e.message))
                }}
              >
                Prepare preview
              </button>
              {job.data && (
                <span className="small muted">
                  {' '}
                  {job.data.status} {job.data.error}
                </span>
              )}
            </div>
          )}
          <div className={styles.controls}>
            <button onClick={() => step(-1)} disabled={!times.data}>
              ‹ 1 frame
            </button>
            <button
              className="primary"
              onClick={() => {
                if (playing) video.current?.pause()
                else
                  void video.current?.play().catch((e) => setError(e.message))
              }}
            >
              <IconPlayerPlay size={15} />
              {playing ? 'Pause' : 'Play'}
            </button>
            <button onClick={() => step(1)} disabled={!times.data}>
              1 frame ›
            </button>
            <input
              aria-label="Playback position"
              type="range"
              min="0"
              max={item.info.duration_ms || 1}
              step="1"
              value={current}
              onChange={(e) => seek(Number(e.target.value))}
            />
            <span className="mono small">
              {time(current)} / {time(item.info.duration_ms || 0)}
            </span>
            <select
              aria-label="Playback speed"
              defaultValue="1"
              onChange={(e) => {
                if (video.current)
                  video.current.playbackRate = Number(e.target.value)
              }}
            >
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
            <button
              className="primary"
              onClick={() => addSplit.current()}
              disabled={draft.source_changed || !draft.duration_ms}
            >
              <IconPlus size={15} />
              Add split point
            </button>
          </div>
        </section>
        {draft.duration_ms > 0 && (
          <Annotation
            draft={draft}
            phases={library.phases}
            currentMs={current}
            onDirty={setDirty}
            registerSave={registerSave}
            registerAdd={registerAdd}
          />
        )}
      </div>
      {tab === 'metadata' && (
        <Metadata
          asset={item}
          onSaved={() => {
            void client.invalidateQueries({ queryKey: ['asset', assetId] })
          }}
        />
      )}
      {tab === 'frames' && <Frames asset={item} />}
      {tab === 'tasks' && (
        <div className="card empty">
          No VLM tasks reference this recording yet.
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {blocker.state === 'blocked' && (
        <Modal
          title="Save annotation before leaving?"
          onClose={() => blocker.reset()}
        >
          <p>Your annotation has unsaved changes.</p>
          <div className="actions">
            <button onClick={() => blocker.reset()}>Stay</button>
            <button
              onClick={() => {
                setDirty(false)
                blocker.proceed()
              }}
            >
              Discard changes
            </button>
            <button
              className="primary"
              onClick={async () => {
                if (await save.current()) blocker.proceed()
              }}
            >
              Save and leave
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

function Metadata({ asset, onSaved }: { asset: Asset; onSaved: () => void }) {
  const [study, setStudy] = useState<Record<string, string>>(asset.study)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const fields: [keyof Study, string, string[]?][] = [
    ['participant', 'Anonymous participant ID'],
    ['trial', 'Trial ID'],
    ['garment', 'Garment', ['shirt', 'jacket']],
    ['condition', 'Condition', ['sighted', 'touch-only']],
    ['split', 'Dataset split', ['development', 'test', 'training']],
    ['overlay', 'RGB overlay', ['clean', 'annotated']],
  ]
  return (
    <section className="card">
      <div className="cardHead">
        <h2>Recording metadata</h2>
      </div>
      <div className="cardBody">
        <dl className={styles.metadata}>
          <dt>File</dt>
          <dd>{asset.path}</dd>
          <dt>Size</dt>
          <dd>
            {(Number(asset.fingerprint.split(':')[0]) / 1024 / 1024).toFixed(1)}{' '}
            MB
          </dd>
          <dt>Resolution</dt>
          <dd>
            {asset.info.width || '—'} × {asset.info.height || '—'}
          </dd>
          <dt>Frame rate</dt>
          <dd>{asset.info.fps?.toFixed(3) || '—'} fps</dd>
          <dt>Time basis</dt>
          <dd>{asset.info.time_basis || 'media_time'}</dd>
          <dt>SHA-256</dt>
          <dd className="mono">{asset.hash}</dd>
        </dl>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setBusy(true)
            void api('/assets/' + asset.id + '/study', 'PUT', study)
              .then(() => {
                setStatus('Saved')
                onSaved()
              })
              .catch((e) => setStatus(e.message))
              .finally(() => setBusy(false))
          }}
        >
          <div className={styles.fields}>
            {fields.map(([key, label, options]) => (
              <label key={key}>
                {label}
                {options ? (
                  <select
                    value={study[key] || ''}
                    onChange={(e) => {
                      setStudy({ ...study, [key]: e.target.value })
                      setStatus('Unsaved')
                    }}
                  >
                    <option value="">Unknown</option>
                    {options.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={study[key] || ''}
                    onChange={(e) => {
                      setStudy({ ...study, [key]: e.target.value })
                      setStatus('Unsaved')
                    }}
                  />
                )}
              </label>
            ))}
          </div>
          <div className="actions">
            <button disabled={busy} className="primary">
              Save metadata
            </button>
            <span role="status">{status}</span>
          </div>
        </form>
      </div>
    </section>
  )
}
