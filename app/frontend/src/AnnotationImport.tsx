import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { IconUpload } from '@tabler/icons-react'
import { api, type ImportPreview, type ImportResult } from './api'
import { Modal } from './components'

const STATUS: Record<ImportPreview['rows'][number]['status'], string> = {
  new: 'Will import',
  conflict: 'Differs from local',
  identical: 'Already the same',
  no_match: 'No matching video',
  ambiguous: 'Ambiguous',
  invalid: 'Invalid',
}

export function AnnotationImport() {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [overwrite, setOverwrite] = useState<string[]>([])
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const form = (chosen: File) => {
    const data = new FormData()
    data.append('file', chosen)
    return data
  }
  const choose = async (chosen: File | undefined) => {
    setFile(chosen || null)
    setPreview(null)
    setOverwrite([])
    setResult(null)
    setError('')
    if (!chosen) return
    setBusy(true)
    try {
      setPreview(
        await api<ImportPreview>(
          '/annotations/import-preview',
          'POST',
          form(chosen),
        ),
      )
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const apply = async () => {
    if (!file || !preview) return
    setBusy(true)
    setError('')
    try {
      const data = form(file)
      data.append('token', preview.token)
      overwrite.forEach((id) => data.append('overwrite', id))
      setResult(await api<ImportResult>('/annotations/import', 'POST', data))
      setPreview(null)
      void client.invalidateQueries({ queryKey: ['library'] })
      void client.invalidateQueries({ queryKey: ['annotation'] })
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const writes = (preview?.counts.new || 0) + overwrite.length
  return (
    <>
      <button
        onClick={() => {
          setOpen(true)
          void choose(undefined)
        }}
      >
        <IconUpload size={16} />
        Import annotations
      </button>
      {open && (
        <Modal
          title="Import annotations"
          onClose={() => {
            if (!busy) setOpen(false)
          }}
        >
          <p className="small muted">
            Choose a CSV or JSON file from Export annotations. Records are
            matched to recordings in data/ by video content, so filenames may
            differ. Nothing is written until you confirm.
          </p>
          <input
            type="file"
            accept=".json,.csv,application/json,text/csv"
            disabled={busy}
            onChange={(e) => void choose(e.target.files?.[0])}
          />
          {busy && !preview && <p>Reading file…</p>}
          {preview && (
            <>
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Recording</th>
                      <th>Segments</th>
                      <th>Result</th>
                      <th>Overwrite</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row) => (
                      <tr key={row.index}>
                        <td className="mono small">
                          {row.local_path || row.video_id}
                          {row.local_path &&
                            row.local_path !== row.video_id && (
                              <span className="muted">
                                {' '}
                                (exported as {row.video_id})
                              </span>
                            )}
                        </td>
                        <td>
                          {row.segment_count}
                          {row.unlabeled_count > 0 &&
                            ` · ${row.unlabeled_count} unlabeled`}
                        </td>
                        <td className="small">
                          <b>{STATUS[row.status]}</b> · {row.message}
                        </td>
                        <td>
                          {row.status === 'conflict' && row.asset_id && (
                            <input
                              type="checkbox"
                              aria-label={'Overwrite ' + row.local_path}
                              checked={overwrite.includes(row.asset_id)}
                              onChange={(e) =>
                                setOverwrite(
                                  e.target.checked
                                    ? [...overwrite, row.asset_id!]
                                    : overwrite.filter(
                                        (id) => id !== row.asset_id,
                                      ),
                                )
                              }
                            />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="actions">
                <button
                  className="primary"
                  disabled={busy || !writes}
                  onClick={() => void apply()}
                >
                  Import {writes} annotation{writes === 1 ? '' : 's'}
                </button>
                <span className="small muted">
                  Local annotations that differ are kept unless you tick
                  Overwrite.
                </span>
              </div>
            </>
          )}
          {result && (
            <p role="status">
              Imported {result.imported} · skipped {result.skipped}
            </p>
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
