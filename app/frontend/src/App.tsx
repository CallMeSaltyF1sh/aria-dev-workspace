import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconFolders,
  IconFileText,
  IconChecklist,
  IconChartBar,
  IconVideo,
} from '@tabler/icons-react'
import { api, type Library } from './api'
import { LibraryPage } from './Library'
import { DetailPage } from './Detail'
import { PromptPage } from './PromptLibrary'
import styles from './App.module.css'

export function App() {
  const location = useLocation()
  const client = useQueryClient()
  const [scanError, setScanError] = useState('')
  const library = useQuery({
    queryKey: ['library'],
    queryFn: () => api<Library>('/library'),
  })
  const scan = async () => {
    setScanError('')
    try {
      client.setQueryData(['library'], await api<Library>('/scan', 'POST'))
    } catch (error) {
      setScanError((error as Error).message)
    }
  }
  const assetId = location.pathname.match(/^\/data\/([^/]+)/)?.[1]
  const navigation = [
    ['/data', 'Data Library', IconFolders],
    ['/prompts', 'Prompt Library', IconFileText],
    ['/tasks', 'VLM Tasks', IconChecklist],
    ['/evaluation', 'Evaluation', IconChartBar],
  ] as const
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <Link to="/data" className={styles.brand}>
          <IconVideo size={20} />
          Dev Workspace
        </Link>
        <nav>
          {navigation.map(([path, label, Icon]) => (
            <Link
              key={path}
              to={path}
              className={
                location.pathname.startsWith(path) ||
                (path === '/data' && location.pathname === '/')
                  ? styles.active
                  : ''
              }
            >
              <Icon size={18} />
              {label}
            </Link>
          ))}
        </nav>
        <span className={styles.local}>Local workspace</span>
      </aside>
      <main>
        <header className={styles.topbar}>
          <span>
            Workspace /{' '}
            {assetId
              ? 'Video detail'
              : navigation.find(([path]) =>
                  location.pathname.startsWith(path),
                )?.[1] || 'Data Library'}
          </span>
          <span className="badge">Local files</span>
        </header>
        <div className={styles.page}>
          {scanError && (
            <p role="alert" className="error">
              {scanError}
            </p>
          )}
          {library.isPending ? (
            <p>Loading recordings…</p>
          ) : library.isError ? (
            <p role="alert">{library.error.message}</p>
          ) : assetId ? (
            <DetailPage
              key={assetId}
              assetId={assetId}
              library={library.data}
            />
          ) : location.pathname === '/data' || location.pathname === '/' ? (
            <LibraryPage library={library.data} scan={scan} />
          ) : location.pathname.startsWith('/prompts') ? (
            <PromptPage />
          ) : (
            <>
              <h1>
                {
                  navigation.find(([path]) =>
                    location.pathname.startsWith(path),
                  )?.[1]
                }
              </h1>
              <div className="card empty">
                This module is planned for the next development phase.
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
