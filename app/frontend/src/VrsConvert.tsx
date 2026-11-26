import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconEye,
  IconFileCode,
  IconHandStop,
  IconMovie,
  IconRefresh,
  IconVideo,
  IconVolume,
} from '@tabler/icons-react'
import { api, type Job, type VrsFile } from './api'
import { Modal } from './components'
import styles from './VrsConvert.module.css'

const STAGES: Record<string, string> = {
  audio: 'Mixing audio',
  frames: 'Reading frames',
  encoding: 'Encoding MP4',
  validating: 'Checking source',
}
const running = (job?: Job | null) =>
  ['queued', 'running'].includes(job?.status || '')
const megabytes = (bytes: number) => (bytes / 1024 / 1024).toFixed(0) + ' MB'

// Aria RGB is 4:3 in every profile; null keeps the recorded resolution.
const WIDTHS = [1920, 1280, 960, 640] as const
type Width = (typeof WIDTHS)[number] | null

type Options = {
  audio: boolean
  eye_gaze: boolean
  hands: boolean
  width: Width
}

const DEFAULTS: Options = {
  audio: true,
  eye_gaze: true,
  hands: true,
  width: null,
}
const STORAGE_KEY = 'devworkspace.vrs.options'

function remembered(): Options {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (!value || typeof value !== 'object') return DEFAULTS
    return {
      audio: Boolean(value.audio),
      eye_gaze: Boolean(value.eye_gaze),
      hands: Boolean(value.hands),
      width: WIDTHS.find((w) => w === value.width) ?? null,
    }
  } catch {
    return DEFAULTS
  }
}

function summarise(
  options: Omit<Options, 'width'> & { width?: number | null },
) {
  return [
    options.width ? `${options.width} px wide` : 'original size',
    options.audio ? 'audio +30 dB' : 'no audio',
    options.eye_gaze && 'gaze overlay',
    options.hands && 'hand overlay',
  ]
    .filter(Boolean)
    .join(' · ')
}

function status(file: VrsFile) {
  const job = file.job
  if (running(job)) {
    const { completed, total, stage } = job?.progress || {}
    const label = STAGES[String(stage)] || 'Starting'
    return total ? `${label} ${completed} / ${total}…` : label + '…'
  }
  if (file.mp4_exists) return 'Converted'
  if (job?.status === 'failed' || job?.status === 'interrupted')
    return 'Failed: ' + (job.error || job.status)
  return 'Not converted'
}

export function VrsPage() {
  const client = useQueryClient()
  const [target, setTarget] = useState<VrsFile | null>(null)
  const [draft, setDraft] = useState<Options>(DEFAULTS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const files = useQuery({
    queryKey: ['vrs'],
    queryFn: () => api<VrsFile[]>('/vrs'),
    staleTime: 0,
    refetchInterval: (q) =>
      q.state.data?.some((f) => running(f.job)) ? 1000 : false,
  })
  const converting = files.data?.filter((f) => running(f.job)).length || 0
  useEffect(() => {
    // A finished conversion adds an MP4 to Data Library.
    if (!converting) void client.invalidateQueries({ queryKey: ['library'] })
  }, [converting, client])
  const open = (file: VrsFile) => {
    setTarget(file)
    setDraft(remembered())
    setError('')
    setBusy(false)
  }
  const convert = async () => {
    if (!target) return
    setBusy(true)
    setError('')
    try {
      await api<Job>(
        '/vrs/' + encodeURIComponent(target.name) + '/convert',
        'POST',
        draft,
      )
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(draft))
      } catch {
        // Private browsing or a full quota: the defaults still work.
      }
      setTarget(null)
      await files.refetch()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const exportFolder = target?.name.slice(0, -'.vrs'.length) || ''
  return (
    <>
      <h1>VRS → MP4</h1>
      <p className="small muted">
        Converts Aria recordings in the repository&apos;s <code>vrs/</code>{' '}
        folder into MP4s in <code>data/</code>, where they appear in Data
        Library for annotation. The MP4 keeps the real DEVICE_TIME frame
        spacing; eye gaze and hand tracking can be drawn onto the video. Each
        recording keeps its own export settings; RGB video is always included.
      </p>
      <section className="card">
        <div className="cardHead">
          <h2>vrs/ · {files.data?.length ?? '…'}</h2>
          <button onClick={() => void files.refetch()}>
            <IconRefresh size={15} />
            Rescan
          </button>
        </div>
        {files.isPending ? (
          <p className="empty">Reading vrs/…</p>
        ) : files.isError ? (
          <p className="error cardBody">{files.error.message}</p>
        ) : !files.data.length ? (
          <p className="empty">
            No VRS files. Copy recordings into the repository&apos;s{' '}
            <code>vrs/</code> folder, then rescan.
          </p>
        ) : (
          <div className="tableScroll">
            <table>
              <thead>
                <tr>
                  <th>Recording</th>
                  <th>Size</th>
                  <th>Status</th>
                  <th>Output</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {files.data.map((file) => (
                  <tr key={file.name}>
                    <td className="mono small">{file.name}</td>
                    <td className="small">{megabytes(file.size)}</td>
                    <td className="small">{status(file)}</td>
                    <td className="small">
                      <div className="actions">
                        {file.mp4_asset_id ? (
                          <Link to={'/data/' + file.mp4_asset_id}>
                            data/{file.mp4}
                          </Link>
                        ) : (
                          file.mp4_exists && (
                            <span className="mono">data/{file.mp4}</span>
                          )
                        )}
                      </div>
                      {file.export && (
                        <div className="muted" style={{ marginTop: 4 }}>
                          {summarise(file.export.settings)}
                        </div>
                      )}
                    </td>
                    <td>
                      <button
                        className="primary"
                        disabled={running(file.job) || file.mp4_exists}
                        title={
                          file.mp4_exists
                            ? `data/${file.mp4} exists. Delete or rename it in Data Library to convert again.`
                            : undefined
                        }
                        onClick={() => open(file)}
                      >
                        Convert
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {target && (
        <Modal
          title="Convert VRS recording"
          onClose={() => {
            if (!busy) setTarget(null)
          }}
        >
          <form
            className={styles.form}
            onSubmit={(event) => {
              event.preventDefault()
              void convert()
            }}
          >
            <div className={styles.sourceCard}>
              <div className={styles.sourceIcon} aria-hidden="true">
                <IconVideo size={17} />
              </div>
              <div className={styles.sourceMeta}>
                <span className={`${styles.sourceName} mono`}>
                  vrs/{target.name}
                </span>
                <span className={styles.sourceSub}>
                  {megabytes(target.size)} · Exports to{' '}
                  <span className="mono">data/{target.mp4}</span>
                </span>
              </div>
            </div>

            <div>
              <div className={styles.sectionLabel}>
                <span>Streams &amp; sensor exports</span>
              </div>
              <div className={styles.optionList}>
                <div className={styles.optionItem}>
                  <div className={`${styles.optionRow} ${styles.optionStatic}`}>
                    <input
                      type="checkbox"
                      checked
                      disabled
                      aria-label="RGB video (always included)"
                    />
                    <div className={styles.optionBody}>
                      <div className={styles.optionHead}>
                        <span className={styles.optionTitle}>
                          <IconMovie size={15} />
                          RGB video
                        </span>
                        <span className="badge">Always included</span>
                      </div>
                      <p className={styles.optionDesc}>
                        Preserves real DEVICE_TIME frame spacing for timeline
                        annotation.
                      </p>
                    </div>
                  </div>
                  <div className={styles.gainBox}>
                    <div className={styles.gainLabel}>
                      <span>Resolution</span>
                      <span className={styles.gainHint}>
                        Smaller files convert and load faster; never upscaled
                      </span>
                    </div>
                    <select
                      aria-label="Video resolution"
                      disabled={busy}
                      value={draft.width ?? ''}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          width: e.target.value
                            ? (Number(e.target.value) as Width)
                            : null,
                        })
                      }
                    >
                      <option value="">Original</option>
                      {WIDTHS.map((w) => (
                        <option key={w} value={w}>
                          {w} × {(w * 3) / 4}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className={styles.optionItem}>
                  <label className={styles.optionRow}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={draft.audio}
                      onChange={(e) =>
                        setDraft({ ...draft, audio: e.target.checked })
                      }
                    />
                    <div className={styles.optionBody}>
                      <span className={styles.optionTitle}>
                        <IconVolume size={15} />
                        Audio track
                      </span>
                      <p className={styles.optionDesc}>
                        All microphones mixed to mono, boosted a fixed 30 dB
                        with a limiter. Contains participants&apos; voices —
                        include only as study consent allows.
                      </p>
                    </div>
                  </label>
                </div>

                <div className={styles.optionItem}>
                  <label className={styles.optionRow}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={draft.eye_gaze}
                      onChange={(e) =>
                        setDraft({ ...draft, eye_gaze: e.target.checked })
                      }
                    />
                    <div className={styles.optionBody}>
                      <span className={styles.optionTitle}>
                        <IconEye size={15} />
                        Eye gaze overlay
                      </span>
                      <p className={styles.optionDesc}>
                        Burns a red circle into the video where the wearer is
                        looking, from the gaze sample nearest each frame.
                      </p>
                    </div>
                  </label>
                </div>

                <div className={styles.optionItem}>
                  <label className={styles.optionRow}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={draft.hands}
                      onChange={(e) =>
                        setDraft({ ...draft, hands: e.target.checked })
                      }
                    />
                    <div className={styles.optionBody}>
                      <span className={styles.optionTitle}>
                        <IconHandStop size={15} />
                        Hand tracking overlay
                      </span>
                      <p className={styles.optionDesc}>
                        Burns each tracked hand&apos;s 21-point skeleton into
                        the video: left hand green, right hand blue.
                      </p>
                    </div>
                  </label>
                </div>
              </div>
            </div>

            <div className={styles.outputBox}>
              <div className={styles.sectionLabel} style={{ marginBottom: 0 }}>
                <span>Output files</span>
                <span className="mono">2 files</span>
              </div>
              <ul className={styles.outputList}>
                <li className={styles.outputItem}>
                  <IconMovie size={14} />
                  <span className={`${styles.outputPath} mono`}>
                    data/<strong>{target.mp4}</strong>
                  </span>
                </li>
                <li className={styles.outputItem}>
                  <IconFileCode size={14} />
                  <span className={`${styles.outputPath} mono`}>
                    workspace/exports/{exportFolder}/
                    <strong>manifest.json</strong>
                  </span>
                </li>
              </ul>
              <p className="muted small" style={{ margin: 0 }}>
                {summarise(draft)}
              </p>
            </div>

            {error && (
              <p className="error" role="alert" style={{ margin: 0 }}>
                {error}
              </p>
            )}

            <div className={styles.footer}>
              <button
                type="button"
                disabled={busy}
                onClick={() => setTarget(null)}
              >
                Cancel
              </button>
              <button className="primary" type="submit" disabled={busy}>
                {busy ? 'Starting…' : 'Convert'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
