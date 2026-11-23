import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import * as Menu from '@radix-ui/react-dropdown-menu'
import {
  IconChevronRight,
  IconDots,
  IconPlus,
  IconRefresh,
} from '@tabler/icons-react'
import { api, time, type Deletion, type Library } from './api'
import { Modal } from './components'
import styles from './Library.module.css'

export function LibraryPage({
  library,
  scan,
}: {
  library: Library
  scan: () => Promise<void>
}) {
  const [params, setParams] = useSearchParams()
  const update = (key: string, value: string) =>
    setParams((previous) => {
      previous.set(key, value)
      return previous
    })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [dialog, setDialog] = useState<{
    kind: 'folder' | 'rename' | 'import'
    path?: string
  } | null>(null)
  const [name, setName] = useState('')
  const [destination, setDestination] = useState('')
  const [deletion, setDeletion] = useState<
    (Deletion & { ids: string[]; directory?: string }) | null
  >(null)
  const [confirmed, setConfirmed] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [keepDuplicate, setKeepDuplicate] = useState(false)
  const [skipExisting, setSkipExisting] = useState(false)
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)
  const client = useQueryClient()
  const firstScan = useRef(false)
  useEffect(() => {
    if (!firstScan.current) {
      firstScan.current = true
      void scan()
    }
  }, [scan])
  const directory = params.get('folder') || ''
  const visible = library.assets
    .filter(
      (asset) =>
        (!directory || asset.path.startsWith(directory + '/')) &&
        asset.path
          .toLowerCase()
          .includes((params.get('q') || '').toLowerCase()) &&
        (!params.get('format') ||
          asset.path.toLowerCase().endsWith(params.get('format')!)) &&
        (!params.get('media') || asset.info.status === params.get('media')) &&
        (!params.get('annotation') ||
          asset.annotation === params.get('annotation')),
    )
    .sort((a, b) =>
      params.get('sort') === 'duration'
        ? (b.info.duration_ms || 0) - (a.info.duration_ms || 0)
        : a.path.localeCompare(b.path),
    )
  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const refresh = async () => {
    client.setQueryData(['library'], await api<Library>('/library'))
  }
  const previewDelete = (ids: string[], directory?: string) =>
    run(async () => {
      const preview = await api<Deletion>('/deletion-preview', 'POST', {
        ids,
        directory,
      })
      setDeletion({ ...preview, ids, directory })
      setConfirmed(false)
    })
  const openFolder = (kind: 'folder' | 'rename', path?: string) => {
    setName(kind === 'rename' ? path!.split('/').at(-1)! : '')
    setDialog({ kind, path })
  }
  return (
    <>
      <div className="pageHead">
        <h1>Data Library</h1>
        <div className="actions">
          <button disabled={busy} onClick={() => run(scan)}>
            <IconRefresh size={16} />
            Scan data/
          </button>
          <button
            className="primary"
            onClick={() => {
              setDestination(directory)
              setDialog({ kind: 'import' })
            }}
          >
            <IconPlus size={16} />
            Add recordings
          </button>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className={styles.layout}>
        <aside className="card">
          <div className="cardHead">
            <h2>Folders</h2>
            <button
              className="iconButton"
              aria-label="New folder"
              onClick={() => openFolder('folder')}
            >
              <IconPlus size={17} />
            </button>
          </div>
          {library.directories.map((path) => (
            <div
              key={path}
              className={styles.folder}
              style={{
                paddingLeft: path
                  ? Math.max(0, path.split('/').length - 1) * 12
                  : 0,
              }}
            >
              <button
                className={path === directory ? styles.chosen : ''}
                onClick={() => update('folder', path)}
                title={path || 'data/'}
              >
                {path ? path.split('/').at(-1) : 'data/'}
                <small>
                  {
                    library.assets.filter(
                      (a) => !path || a.path.startsWith(path + '/'),
                    ).length
                  }
                </small>
              </button>
              {path && (
                <Menu.Root>
                  <Menu.Trigger
                    className="iconButton"
                    aria-label={'Manage ' + path}
                  >
                    <IconDots size={16} />
                  </Menu.Trigger>
                  <Menu.Portal>
                    <Menu.Content className="dropdown">
                      <Menu.Item onSelect={() => openFolder('rename', path)}>
                        Rename
                      </Menu.Item>
                      <Menu.Item
                        onSelect={() => {
                          void previewDelete([], path)
                        }}
                      >
                        Delete folder
                      </Menu.Item>
                    </Menu.Content>
                  </Menu.Portal>
                </Menu.Root>
              )}
            </div>
          ))}
        </aside>
        <section className="card">
          <div className="cardHead">
            <h2>
              Recordings <span className="muted">/ {visible.length}</span>
            </h2>
            <button
              className="danger"
              disabled={!selected.length || busy}
              onClick={() => previewDelete(selected)}
            >
              Delete selected ({selected.length})
            </button>
          </div>
          <div className={styles.filters}>
            <input
              aria-label="Search recordings"
              placeholder="Search recordings"
              value={params.get('q') || ''}
              onChange={(e) => update('q', e.target.value)}
            />
            <select
              aria-label="Format"
              value={params.get('format') || ''}
              onChange={(e) => update('format', e.target.value)}
            >
              <option value="">All formats</option>
              <option value=".mp4">MP4</option>
              <option value=".vrs">VRS</option>
            </select>
            <select
              aria-label="Media status"
              value={params.get('media') || ''}
              onChange={(e) => update('media', e.target.value)}
            >
              <option value="">All media states</option>
              {['ready', 'needs_preview', 'error', 'missing'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <select
              aria-label="Annotation status"
              value={params.get('annotation') || ''}
              onChange={(e) => update('annotation', e.target.value)}
            >
              <option value="">All annotations</option>
              {['not_started', 'saved', 'source_changed'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <select
              aria-label="Sort"
              value={params.get('sort') || ''}
              onChange={(e) => update('sort', e.target.value)}
            >
              <option value="">Name</option>
              <option value="duration">Duration ↓</option>
            </select>
          </div>
          <div className="tableScroll">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Select all visible"
                      checked={
                        visible.length > 0 &&
                        visible.every((a) => selected.includes(a.id))
                      }
                      onChange={(e) =>
                        setSelected(
                          e.target.checked ? visible.map((a) => a.id) : [],
                        )
                      }
                    />
                  </th>
                  <th>Recording</th>
                  <th>Format</th>
                  <th>Duration</th>
                  <th>Media</th>
                  <th>Annotation</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((asset) => {
                  const url = '/data/' + asset.id + '?' + params.toString()
                  const navigation = {
                    order: visible.map((a) => a.id),
                    returnTo: '/data?' + params.toString(),
                  }
                  return (
                    <tr
                      key={asset.id}
                      style={{ cursor: 'pointer' }}
                      onClick={(event) => {
                        if (
                          !(event.target as HTMLElement).closest(
                            'a,input,button',
                          )
                        )
                          void navigate(url, { state: navigation })
                      }}
                    >
                      <td>
                        <input
                          type="checkbox"
                          aria-label={'Select ' + asset.path}
                          checked={selected.includes(asset.id)}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, asset.id]
                                : selected.filter((id) => id !== asset.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <Link
                          className={styles.assetLink}
                          to={url}
                          state={navigation}
                        >
                          {asset.path.split('/').at(-1)}
                          <small className="muted">{asset.path}</small>
                        </Link>
                      </td>
                      <td>
                        <span className="badge">
                          {asset.path.split('.').at(-1)?.toUpperCase()}
                        </span>
                      </td>
                      <td className="mono">
                        {asset.info.duration_ms
                          ? time(asset.info.duration_ms)
                          : '—'}
                      </td>
                      <td>
                        <span className="badge" title={asset.info.error}>
                          {asset.info.status.replaceAll('_', ' ')}
                        </span>
                        {library.assets.some(
                          (a) =>
                            a.id !== asset.id &&
                            a.hash === asset.hash &&
                            !a.missing,
                        ) && <span className="badge">Duplicate content</span>}
                      </td>
                      <td>
                        <span className="badge">
                          {asset.annotation.replaceAll('_', ' ')}
                        </span>
                      </td>
                      <td>
                        <Link
                          aria-label={'Open ' + asset.path}
                          to={url}
                          state={navigation}
                        >
                          <IconChevronRight size={18} />
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {!visible.length && (
            <p className="empty">
              {library.assets.length
                ? 'No recordings match these filters.'
                : 'Add an MP4 or VRS recording to get started.'}
            </p>
          )}
        </section>
      </div>
      {dialog && (
        <Modal
          title={
            dialog.kind === 'import'
              ? 'Add recordings'
              : dialog.kind === 'folder'
                ? 'New folder'
                : 'Rename folder'
          }
          onClose={() => {
            if (!busy) setDialog(null)
          }}
        >
          {dialog.kind === 'import' ? (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void run(async () => {
                  for (const file of files) {
                    const incoming = name || file.name
                    if (
                      skipExisting &&
                      library.assets.some(
                        (a) =>
                          a.path ===
                            [destination, incoming].filter(Boolean).join('/') &&
                          !a.missing,
                      )
                    )
                      continue
                    const body = new FormData()
                    body.set('file', file)
                    body.set('directory', destination)
                    body.set('name', name || file.name)
                    body.set('allow_duplicate', String(keepDuplicate))
                    await api('/import', 'POST', body)
                  }
                  setDialog(null)
                  setFiles([])
                  setName('')
                  await refresh()
                })
              }}
            >
              <label>
                Destination
                <select
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                >
                  {library.directories.map((d) => (
                    <option key={d} value={d}>
                      data/{d}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                MP4 / VRS files
                <input
                  ref={fileInput}
                  type="file"
                  accept=".mp4,.vrs"
                  multiple
                  required
                  onChange={(e) => {
                    setFiles([...(e.target.files || [])])
                    setName('')
                  }}
                />
              </label>
              {files.length === 1 && (
                <label>
                  Incoming filename
                  <input
                    value={name || files[0].name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
              )}
              <label className="check">
                <input
                  type="checkbox"
                  checked={skipExisting}
                  onChange={(e) => setSkipExisting(e.target.checked)}
                />
                Skip existing filenames
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={keepDuplicate}
                  onChange={(e) => setKeepDuplicate(e.target.checked)}
                />
                Keep duplicate content
              </label>
              <button className="primary" disabled={busy}>
                {busy ? 'Importing…' : 'Import'}
              </button>
            </form>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void run(async () => {
                  await api(
                    '/directories',
                    dialog.kind === 'folder' ? 'POST' : 'PATCH',
                    dialog.kind === 'folder'
                      ? { path: [directory, name].filter(Boolean).join('/') }
                      : { path: dialog.path, new_name: name },
                  )
                  setDialog(null)
                  await refresh()
                })
              }}
            >
              <label>
                Folder name
                <input
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <button className="primary" disabled={busy}>
                Save
              </button>
            </form>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </Modal>
      )}
      {deletion && (
        <Modal
          title={'Delete ' + deletion.files.length + ' local files?'}
          onClose={() => {
            if (!busy) setDeletion(null)
          }}
        >
          <p>This directly deletes the actual files from data/.</p>
          <ul className={styles.fileList}>
            {deletion.files.map((path) => (
              <li key={path} className="mono">
                {path}
              </li>
            ))}
          </ul>
          <p>
            {deletion.annotations} annotation(s) and {deletion.frame_groups}{' '}
            frame group(s) will remain as historical records.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I understand these local files will be deleted.
          </label>
          <button
            className="danger"
            disabled={!confirmed || busy}
            onClick={() =>
              run(async () => {
                client.setQueryData(
                  ['library'],
                  await api('/delete', 'POST', deletion),
                )
                setDeletion(null)
                setSelected([])
              })
            }
          >
            Delete files from data/
          </button>
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
