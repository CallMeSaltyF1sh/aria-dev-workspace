import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  type Prompt,
  type PromptInput,
  type PromptPreview,
  type PromptSummary,
} from './api'
import styles from './App.module.css'

const SECTIONS = [
  [
    'context',
    'Context',
    'Who is filmed and what they do. {garment} becomes shirt or jacket.',
  ],
  [
    'phases',
    'Phase definitions',
    'One label per line, starting with P0, P1, P2, P3, P4 and unclear.',
  ],
  [
    'guidance',
    'Guidance',
    'Rules for borderline cases. {garment} is allowed here too.',
  ],
] as const
type Text = Pick<Prompt, 'context' | 'phases' | 'guidance'>

export function PromptPage() {
  const client = useQueryClient()
  const list = useQuery({
    queryKey: ['prompts'],
    queryFn: () => api<PromptSummary[]>('/prompts'),
  })
  const [picked, setPicked] = useState<string | null>(null)
  const [draft, setDraft] = useState<
    (Text & { name: string; note: string }) | null
  >(null)
  const [saved, setSaved] = useState('')
  const id = picked || list.data?.[0]?.id
  const prompt = useQuery({
    queryKey: ['prompt', id],
    enabled: !!id,
    queryFn: () => api<Prompt>('/prompts/' + id),
  })
  if (list.isPending) return <p>Loading prompts…</p>
  if (list.isError) return <p className="error">{list.error.message}</p>
  const open = (next: string) => {
    setPicked(next)
    setDraft(null)
  }
  return (
    <>
      <h1>Prompt Library</h1>
      <p className="small muted">
        Prompts are files in <span className="mono">prompts/</span> in the
        repository. A version is never changed: edit by saving a new version,
        then commit the new file to share it. VLM Run uses the newest version
        unless you choose another.
      </p>
      <div className={styles.promptLayout}>
        <nav className="card" aria-label="Prompt versions">
          <div className="cardHead">
            <h2>Versions</h2>
          </div>
          <ul className={styles.versionList}>
            {list.data.map((p) => (
              <li key={p.id}>
                <button
                  aria-current={p.id === id ? 'true' : undefined}
                  onClick={() => open(p.id)}
                >
                  <b>
                    {p.id} · {p.name}
                  </b>
                  <span className="small muted">
                    {p.based_on ? `from ${p.based_on} · ` : ''}
                    {new Date(p.created_at).toLocaleDateString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="stack">
          {saved && (
            <p role="status" className="card cardBody">
              Saved as <span className="mono">{saved}</span>. Commit it to share
              it with the team.
            </p>
          )}
          {prompt.isPending ? (
            <p>Loading…</p>
          ) : prompt.isError ? (
            <p className="error">{prompt.error.message}</p>
          ) : draft ? (
            <Editor
              base={prompt.data}
              draft={draft}
              onChange={setDraft}
              onCancel={() => setDraft(null)}
              onSaved={(value) => {
                void client.invalidateQueries({ queryKey: ['prompts'] })
                setSaved(value.file)
                open(value.id)
              }}
            />
          ) : (
            <Version
              value={prompt.data}
              onEdit={() => {
                setSaved('')
                setDraft({
                  name: '',
                  note: '',
                  context: prompt.data.context,
                  phases: prompt.data.phases,
                  guidance: prompt.data.guidance,
                })
              }}
            />
          )}
        </div>
      </div>
    </>
  )
}

function Version({ value, onEdit }: { value: Prompt; onEdit: () => void }) {
  return (
    <>
      <section className="card">
        <div className="cardHead">
          <div>
            <h2>
              {value.id} · {value.name}
            </h2>
            <span className="small muted">
              {value.based_on ? `Based on ${value.based_on} · ` : ''}
              {new Date(value.created_at).toLocaleString()} ·{' '}
              <span className="mono">{value.file}</span>
            </span>
          </div>
          <div className="actions">
            <span className="badge mono">{value.hash}</span>
            <button className="primary" onClick={onEdit}>
              New version from {value.id}
            </button>
          </div>
        </div>
        {value.note && <p className="cardBody small">{value.note}</p>}
      </section>
      {SECTIONS.map(([key, label]) => (
        <section className="card" key={key}>
          <div className="cardHead">
            <h2>{label}</h2>
          </div>
          <pre className={styles.prompt}>{value[key]}</pre>
        </section>
      ))}
      <section className="card">
        <div className="cardHead">
          <h2>Full prompt</h2>
          <span className="small muted">
            Example: jacket, 9 frames, 0.5 s apart, target 12.30 s. Frame
            descriptions and the JSON answer format are fixed.
          </span>
        </div>
        <pre className={styles.prompt}>{value.example}</pre>
      </section>
    </>
  )
}

function Editor({
  base,
  draft,
  onChange,
  onCancel,
  onSaved,
}: {
  base: Prompt
  draft: Text & { name: string; note: string }
  onChange: (value: Text & { name: string; note: string }) => void
  onCancel: () => void
  onSaved: (value: Prompt) => void
}) {
  const [text, setText] = useState<Text>(draft)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Re-render the preview once typing pauses, not on every keystroke.
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        setText({
          context: draft.context,
          phases: draft.phases,
          guidance: draft.guidance,
        }),
      400,
    )
    return () => window.clearTimeout(timer)
  }, [draft.context, draft.phases, draft.guidance])
  const preview = useQuery({
    queryKey: ['prompt-preview', text],
    queryFn: () => api<PromptPreview>('/prompts/preview', 'POST', text),
    retry: false,
    placeholderData: (previous) => previous,
  })
  const changed = SECTIONS.filter(([key]) => draft[key] !== base[key]).length
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const body: PromptInput = { ...draft, based_on: base.id }
      onSaved(await api<Prompt>('/prompts', 'POST', body))
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <section className="card">
        <div className="cardHead">
          <h2>New version from {base.id}</h2>
          <span className="small muted">
            {changed
              ? `${changed} section${changed === 1 ? '' : 's'} changed`
              : 'No changes yet'}
          </span>
        </div>
        <div className="cardBody">
          <label>
            Name
            <input
              value={draft.name}
              placeholder="e.g. Stricter P1 vs P3"
              onChange={(e) => onChange({ ...draft, name: e.target.value })}
            />
          </label>
          <label>
            What changed and why
            <input
              value={draft.note}
              placeholder="Optional note for teammates"
              onChange={(e) => onChange({ ...draft, note: e.target.value })}
            />
          </label>
          {SECTIONS.map(([key, label, hint]) => (
            <label key={key}>
              <span>
                {label}
                {draft[key] !== base[key] && (
                  <span className="badge"> changed</span>
                )}
              </span>
              <textarea
                className={styles.promptInput}
                rows={key === 'phases' ? 10 : 4}
                value={draft[key]}
                onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
              />
              <span className="small muted">{hint}</span>
            </label>
          ))}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <button
              className="primary"
              disabled={busy || !changed || !draft.name.trim()}
              onClick={() => void save()}
            >
              Save as new version
            </button>
            <button disabled={busy} onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="cardHead">
          <h2>Preview</h2>
          {preview.data && !preview.isError && (
            <span className="badge mono">{preview.data.hash}</span>
          )}
        </div>
        {preview.isError ? (
          <p className="error cardBody" role="alert">
            {preview.error.message}
          </p>
        ) : (
          <pre className={styles.prompt}>
            {preview.data?.example || 'Rendering…'}
          </pre>
        )}
      </section>
    </>
  )
}
