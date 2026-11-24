import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { IconDownload } from '@tabler/icons-react'
import { api, type ExportSummary } from './api'
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
  const suffix = assetId ? '?asset_id=' + encodeURIComponent(assetId) : ''
  const summary = useQuery({
    queryKey: ['annotation-export', assetId],
    enabled: open,
    queryFn: () => api<ExportSummary>('/annotations/export-summary' + suffix),
    staleTime: 0,
  })
  const download = async (format: 'csv' | 'json') => {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(
        '/api/annotations/export?format=' +
          format +
          (assetId ? '&asset_id=' + encodeURIComponent(assetId) : ''),
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
  return (
    <>
      <button
        disabled={disabled}
        title={disabledHint}
        onClick={() => {
          setOpen(true)
          setError('')
          void summary.refetch()
        }}
      >
        <IconDownload size={16} />
        {assetId ? 'Export' : 'Export annotations'}
      </button>
      {open && (
        <Modal
          title={assetId ? 'Export annotation' : 'Export all annotations'}
          onClose={() => {
            if (!busy) setOpen(false)
          }}
        >
          <p className="small muted">
            {assetId ? 'Saved annotation' : 'All folders · saved annotations'}
          </p>
          {summary.isPending || summary.isFetching ? (
            <p>Loading…</p>
          ) : summary.isError ? (
            <p className="error" role="alert">
              {summary.error.message}
            </p>
          ) : (
            <>
              <p>
                {summary.data.recording_count} recording
                {summary.data.recording_count === 1 ? '' : 's'} ·{' '}
                {summary.data.segment_count} segment
                {summary.data.segment_count === 1 ? '' : 's'} ·{' '}
                {summary.data.unlabeled_count} unlabeled
              </p>
              {(summary.data.changed_source_count > 0 ||
                summary.data.missing_source_count > 0) && (
                <p className="error">
                  {summary.data.changed_source_count} changed sources ·{' '}
                  {summary.data.missing_source_count} missing sources
                </p>
              )}
              {!summary.data.recording_count && (
                <p>No saved annotations with labeled segments.</p>
              )}
              <div className="actions">
                <button
                  disabled={busy || !summary.data.recording_count}
                  onClick={() => void download('csv')}
                >
                  Export CSV
                </button>
                <button
                  className="primary"
                  disabled={busy || !summary.data.recording_count}
                  onClick={() => void download('json')}
                >
                  Export JSON
                </button>
              </div>
            </>
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
