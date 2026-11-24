import { useQuery } from '@tanstack/react-query'
import { api, type VlmPrompt } from './api'
import styles from './App.module.css'

export function PromptPage() {
  const prompt = useQuery({
    queryKey: ['vlm-prompt'],
    queryFn: () => api<VlmPrompt>('/vlm/prompt'),
  })
  if (prompt.isPending) return <p>Loading prompt…</p>
  if (prompt.isError) return <p className="error">{prompt.error.message}</p>
  const value = prompt.data
  return (
    <>
      <h1>Prompt Library</h1>
      <div className="stack">
        <section className="card">
          <div className="cardHead">
            <h2>Sliding-window phase prompt</h2>
            <span className="badge mono">Read-only · {value.hash}</span>
          </div>
          <div className="cardBody">
            <p className="small muted">
              Every VLM Run sends this prompt. Its hash is saved with each run,
              so results can be traced to the exact text. Editing, versions and
              A/B tests are planned; for now change it in{' '}
              <span className="mono">{value.file}</span> and restart.
            </p>
            <p className="small">
              Source: {value.source} · mode {value.mode} · allowed labels{' '}
              <span className="mono">{value.labels.join(', ')}</span>
            </p>
          </div>
        </section>
        <section className="card">
          <div className="cardHead">
            <h2>Phase definitions</h2>
            <span className="small muted">
              Inserted at <span className="mono">{'{phases}'}</span>
            </span>
          </div>
          <pre className={styles.prompt}>{value.phases}</pre>
        </section>
        <section className="card">
          <div className="cardHead">
            <h2>Template</h2>
          </div>
          <div className="cardBody small muted">
            Filled per target point: <span className="mono">{'{garment}'}</span>{' '}
            from the run settings or Metadata,{' '}
            <span className="mono">{'{n}'}</span> frames sent,{' '}
            <span className="mono">{'{step}'}</span> seconds between frames,{' '}
            <span className="mono">{'{target}'}</span> actual target time. After
            the text, each frame follows as <span className="mono">t=…s</span>{' '}
            (the target marked <span className="mono">[TARGET]</span>) plus its
            image. An invalid answer gets one retry with a reminder of the
            allowed labels.
          </div>
          <pre className={styles.prompt}>{value.template}</pre>
        </section>
      </div>
    </>
  )
}
