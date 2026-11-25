import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { IconDownload } from '@tabler/icons-react'
import { api, type ExportItem, type ExportSummary } from './api'
import { Modal } from './components'

export function AnnotationExport({
  assetId,
  disabled = false,
  disabledHint,
}: {
  assetId?: string
  disabled?: boolean
  disabledHint?: string
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Library export: everything is selected until the user unticks it.
  const [excluded, setExcluded] = useState<string[]>([])
  const suffix = assetId ? '?asset_id=' + encodeURIComponent(assetId) : ''
  const summary = useQuery({
    queryKey: ['annotation-export', assetId],
    enabled: open && !!assetId,
    queryFn: () => api<ExportSummary>('/annotations/export-summary' + suffix),
    staleTime: 0,
  })
  const items = useQuery({
    queryKey: ['annotation-exportable'],
    enabled: open && !assetId,
    queryFn: () => api<ExportItem[]>('/annotations/exportable'),
    staleTime: 0,
  })
  const chosen = (items.data || []).filter(
    (item) => !excluded.includes(item.asset_id),
  )
  const ids = assetId ? [assetId] : chosen.map((item) => item.asset_id)
  const download = async (format: 'csv' | 'json') => {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(
        '/api/annotations/export?format=' +
          format +
          ids.map((id) => '&asset_id=' + encodeURIComponent(id)).join(''),
      )
      if (!response.ok) {
        const value = await response.json()
        throw new Error(value.detail || 'Export failed.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download =
        response.headers
          .get('Content-Disposition')
          ?.match(/filename="([^"]+)"/)?.[1] || 'annotations.' + format
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 10000)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const counts = assetId
    ? summary.data
    : items.data && {
        recording_count: chosen.length,
        segment_count: chosen.reduce((n, i) => n + i.segment_count, 0),
        unlabeled_count: chosen.reduce((n, i) => n + i.unlabeled_count, 0),
        changed_source_count: chosen.filter(
          (i) => i.source_status === 'changed',
        ).length,
        missing_source_count: chosen.filter(
          (i) => i.source_status === 'missing',
        ).length,
      }
  const loading = assetId
    ? summary.isPending || summary.isFetching
    : items.isPending || items.isFetching
  const failure = assetId ? summary.error : items.error
  const plural = (n: number, word: string) =>
    `${n} ${word}${n === 1 ? '' : 's'}`
  return (
    <>
      <button
        disabled={disabled}
        title={disabledHint}
        onClick={() => {
          setOpen(true)
          setError('')
          setExcluded([])
          void (assetId ? summary.refetch() : items.refetch())
        }}
      >
        <IconDownload size={16} />
        {assetId ? 'Export' : 'Export annotations'}
      </button>
      {open && (
        <Modal
          title={assetId ? 'Export annotation' : 'Export annotations'}
          onClose={() => {
            if (!busy) setOpen(false)
          }}
        >
          {loading ? (
            <p>Loading…</p>
          ) : failure ? (
            <p className="error" role="alert">
              {failure.message}
            </p>
          ) : (
            counts && (
              <>
                {assetId ? (
                  <p className="small muted">Saved annotation</p>
                ) : !items.data?.length ? (
                  <p>No saved annotations with labeled segments.</p>
                ) : (
                  <>
                    <div className="actions spread">
                      <p className="small muted" style={{ margin: 0 }}>
                        {plural(items.data.length, 'recording')} annotated ·{' '}
                        {chosen.length} selected
                      </p>
                      <div className="actions">
                        <button
                          className="textButton"
                          disabled={!excluded.length}
                          onClick={() => setExcluded([])}
                        >
                          Select all
                        </button>
                        <button
                          className="textButton"
                          disabled={!chosen.length}
                          onClick={() =>
                            setExcluded(items.data.map((i) => i.asset_id))
                          }
                        >
                          Clear
                        </button>
                      </div>
                    </div>
                    <div
                      className="tableScroll"
                      style={{ maxHeight: 320, overflowY: 'auto' }}
                    >
                      <table>
                        <thead>
                          <tr>
                            <th>Include</th>
                            <th>Recording</th>
                            <th>Segments</th>
                            <th>Saved</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.data.map((item) => (
                            <tr key={item.asset_id}>
                              <td>
                                <input
                                  type="checkbox"
                                  aria-label={'Include ' + item.video_id}
                                  checked={!excluded.includes(item.asset_id)}
                                  onChange={(e) =>
                                    setExcluded(
                                      e.target.checked
                                        ? excluded.filter(
                                            (id) => id !== item.asset_id,
                                          )
                                        : [...excluded, item.asset_id],
                                    )
                                  }
                                />
                              </td>
                              <td className="mono small">
                                {item.video_id}
                                {item.source_status !== 'current' && (
                                  <span className="error">
                                    {' '}
                                    · source {item.source_status}
                                  </span>
                                )}
                              </td>
                              <td>
                                {item.segment_count}
                                {item.unlabeled_count > 0 &&
                                  ` · ${item.unlabeled_count} unlabeled`}
                              </td>
                              <td className="small muted">
                                {item.saved_at
                                  ? new Date(item.saved_at).toLocaleString()
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
                {(assetId || chosen.length > 0) && (
                  <p>
                    {plural(counts.recording_count, 'recording')} ·{' '}
                    {plural(counts.segment_count, 'segment')} ·{' '}
                    {counts.unlabeled_count} unlabeled
                  </p>
                )}
                {(counts.changed_source_count > 0 ||
                  counts.missing_source_count > 0) && (
                  <p className="error">
                    {counts.changed_source_count} changed sources ·{' '}
                    {counts.missing_source_count} missing sources
                  </p>
                )}
                {assetId && !counts.recording_count && (
                  <p>No saved annotations with labeled segments.</p>
                )}
                <div className="actions">
                  <button
                    disabled={busy || !counts.recording_count}
                    onClick={() => void download('csv')}
                  >
                    Export CSV
                  </button>
                  <button
                    className="primary"
                    disabled={busy || !counts.recording_count}
                    onClick={() => void download('json')}
                  >
                    Export JSON
                  </button>
                </div>
              </>
            )
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </Modal>
      )}
    </>
  )
}
