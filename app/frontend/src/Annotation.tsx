import { useEffect, useReducer, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, time, type Draft, type Interval, type Library } from './api'
import styles from './Detail.module.css'
import { AnnotationExport } from './AnnotationExport'

type Action =
  | { type: 'label'; index: number; phase: Interval['phase'] }
  | { type: 'split'; at: number }
  | { type: 'move'; index: number; at: number }
  | { type: 'remove'; index: number }
  | { type: 'reset'; intervals: Interval[] }
function edit(intervals: Interval[], action: Action): Interval[] {
  if (action.type === 'reset') return action.intervals
  const next = intervals.map((i) => ({ ...i }))
  if (action.type === 'label') {
    next[action.index].phase = action.phase
    return next
  }
  if (action.type === 'split') {
    const at = Math.round(action.at / 100) * 100
    const index = next.findIndex((i) => i.start_ms < at && at < i.end_ms)
    if (index < 0) return intervals
    const item = next[index]
    if (
      at - item.start_ms < 100 ||
      (item.end_ms - at < 100 && index < next.length - 1)
    )
      return intervals
    next.splice(index, 1, { ...item, end_ms: at }, { ...item, start_ms: at })
    return next
  }
  const left = next[action.index],
    right = next[action.index + 1]
  if (!left || !right) return intervals
  if (action.type === 'remove') {
    next.splice(action.index, 2, {
      start_ms: left.start_ms,
      end_ms: right.end_ms,
      phase: left.phase === right.phase ? left.phase : null,
    })
  } else {
    const max = right.end_ms - (action.index + 1 === next.length - 1 ? 1 : 100)
    const at = Math.max(
      left.start_ms + 100,
      Math.min(Math.floor(max / 100) * 100, Math.round(action.at / 100) * 100),
    )
    left.end_ms = at
    right.start_ms = at
  }
  return next
}

export function Annotation({
  draft,
  phases,
  onDirty,
  registerSave,
  registerAdd,
}: {
  draft: Draft
  phases: Library['phases']
  onDirty: (dirty: boolean) => void
  registerSave: (save: () => Promise<boolean>) => void
  registerAdd: (add: (atMs: number) => void) => void
}) {
  const [intervals, dispatch] = useReducer(edit, draft.intervals)
  const client = useQueryClient()
  const [saved, setSaved] = useState(draft)
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const axis = useRef<HTMLDivElement>(null)
  const root = useRef<HTMLElement>(null)
  const dragging = useRef<{ index: number; x: number; at: number } | null>(null)
  const operation = useRef(false)
  const busy = saving || restoring
  const dirty = JSON.stringify(intervals) !== JSON.stringify(saved.intervals)
  useEffect(() => onDirty(dirty), [dirty, onDirty])
  useEffect(() => {
    const clear = (event: PointerEvent) => {
      if (
        !(event.target as HTMLElement).closest(
          '[aria-label^="Split point"],button[data-delete-split]',
        )
      )
        setSelected(null)
    }
    document.addEventListener('pointerdown', clear)
    return () => document.removeEventListener('pointerdown', clear)
  }, [])
  const save = async () => {
    if (operation.current) return false
    operation.current = true
    setSaving(true)
    setError('')
    try {
      await client.cancelQueries({
        queryKey: ['annotation', draft.asset_id],
        exact: true,
      })
      const value = await api<Draft>(
        '/assets/' + draft.asset_id + '/annotation',
        'PUT',
        { revision: saved.revision, intervals },
      )
      setSaved(value)
      client.setQueryData(['annotation', draft.asset_id], value)
      void client.invalidateQueries({ queryKey: ['library'] })
      return true
    } catch (error) {
      setError((error as Error).message)
      return false
    } finally {
      operation.current = false
      setSaving(false)
    }
  }
  const restore = async () => {
    if (operation.current || !dirty) return
    operation.current = true
    setRestoring(true)
    setError('')
    try {
      await client.cancelQueries({
        queryKey: ['annotation', draft.asset_id],
        exact: true,
      })
      const value = await api<Draft>(
        '/assets/' + draft.asset_id + '/annotation',
      )
      setSaved(value)
      dispatch({ type: 'reset', intervals: value.intervals })
      client.setQueryData(['annotation', draft.asset_id], value)
      setSelected(null)
      dragging.current = null
      onDirty(false)
      void client.invalidateQueries({ queryKey: ['library'] })
    } catch (error) {
      setError((error as Error).message)
    } finally {
      operation.current = false
      setRestoring(false)
    }
  }
  useEffect(() => {
    registerSave(save)
    registerAdd((atMs) => {
      if (draft.source_changed || operation.current) return
      const at = Math.round(atMs / 100) * 100
      const existing = intervals
        .slice(0, -1)
        .findIndex((item) => item.end_ms === at)
      if (existing >= 0) {
        setSelected(existing)
        return
      }
      const index = intervals.findIndex(
        (item) => item.start_ms < at && at < item.end_ms,
      )
      if (index < 0) return
      dispatch({ type: 'split', at })
      setSelected(index)
    })
  }) // Parent navigation always uses the current editor snapshot.
  const coordinate = (x: number) => {
    const rect = axis.current!.getBoundingClientRect()
    return ((x - rect.left) / rect.width) * draft.duration_ms
  }
  return (
    <section className="card" ref={root}>
      <div
        className="cardHead"
        onPointerDown={(event) => {
          if (!(event.target as HTMLElement).closest('button'))
            setSelected(null)
        }}
      >
        <h2>Annotation</h2>
        <div className="actions">
          <span className="muted small">
            {restoring
              ? 'Restoring…'
              : saving
                ? 'Saving…'
                : dirty
                  ? 'Unsaved'
                  : saved.revision
                    ? 'Saved'
                    : 'Not started'}
          </span>
          <AnnotationExport
            assetId={draft.asset_id}
            disabled={dirty || busy || !saved.revision}
            disabledHint={
              dirty
                ? 'Save changes before exporting.'
                : !saved.revision
                  ? 'Save an annotation first.'
                  : undefined
            }
          />
          <button
            disabled={busy || !dirty}
            onClick={() => void restore()}
            title="Discard edits and restore the latest saved annotation. Without a saved annotation, reset to an unlabeled timeline."
          >
            Restore
          </button>
          <button
            data-delete-split
            className="danger"
            disabled={selected === null || busy || draft.source_changed}
            onClick={() => {
              if (selected !== null)
                dispatch({ type: 'remove', index: selected })
              setSelected(null)
            }}
          >
            Delete split point
          </button>
          <button
            className="primary"
            disabled={
              busy || draft.source_changed || (!dirty && !!saved.revision)
            }
            onClick={save}
          >
            Save
          </button>
        </div>
      </div>
      <div
        className="cardBody"
        onPointerDown={(event) => {
          if (!(event.target as HTMLElement).closest('button,input,select'))
            setSelected(null)
        }}
      >
        {draft.source_changed && (
          <p className="error">
            Source changed. Existing annotation requires review before saving.
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className={styles.axisLabels}>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <span key={f}>{time(draft.duration_ms * f)}</span>
          ))}
        </div>
        <div
          className={styles.axis}
          ref={axis}
          onClick={(event) => {
            if (event.target === axis.current) {
              if (selected !== null) setSelected(null)
              else if (!draft.source_changed && !operation.current)
                dispatch({ type: 'split', at: coordinate(event.clientX) })
            }
          }}
        >
          {intervals.slice(0, -1).map((segment, index) => (
            <button
              key={index}
              aria-label={'Split point ' + time(segment.end_ms)}
              aria-pressed={selected === index}
              className={styles.boundary}
              style={{ left: (segment.end_ms / draft.duration_ms) * 100 + '%' }}
              disabled={draft.source_changed || busy}
              onClick={(event) => {
                event.stopPropagation()
                setSelected(index)
              }}
              onPointerDown={(event) => {
                event.stopPropagation()
                setSelected(index)
                event.currentTarget.setPointerCapture(event.pointerId)
                dragging.current = {
                  index,
                  x: event.clientX,
                  at: segment.end_ms,
                }
              }}
              onPointerMove={(event) => {
                const drag = dragging.current
                if (drag?.index === index)
                  dispatch({
                    type: 'move',
                    index,
                    at:
                      drag.at + coordinate(event.clientX) - coordinate(drag.x),
                  })
              }}
              onPointerUp={() => {
                dragging.current = null
              }}
              onLostPointerCapture={() => {
                dragging.current = null
              }}
              onKeyDown={(event) => {
                if (
                  ['ArrowLeft', 'ArrowRight', 'Delete', 'Backspace'].includes(
                    event.key,
                  )
                ) {
                  event.preventDefault()
                  setSelected(index)
                  if (event.key === 'Delete' || event.key === 'Backspace') {
                    dispatch({ type: 'remove', index })
                    setSelected(null)
                  } else
                    dispatch({
                      type: 'move',
                      index,
                      at:
                        segment.end_ms +
                        (event.key === 'ArrowLeft' ? -100 : 100),
                    })
                }
              }}
            >
              <span className={styles.bubble}>{time(segment.end_ms)}</span>
            </button>
          ))}
        </div>
        <div className={styles.segments}>
          {intervals.map((segment, index) => (
            <select
              key={index}
              aria-label={
                'Phase ' +
                time(segment.start_ms) +
                ' to ' +
                time(segment.end_ms)
              }
              value={segment.phase || ''}
              disabled={draft.source_changed || busy}
              style={{
                width:
                  ((segment.end_ms - segment.start_ms) / draft.duration_ms) *
                    100 +
                  '%',
                background: segment.phase
                  ? phases[segment.phase].color
                  : '#fafafa',
              }}
              onChange={(e) =>
                dispatch({
                  type: 'label',
                  index,
                  phase: (e.target.value || null) as Interval['phase'],
                })
              }
            >
              <option value="">Choose phase</option>
              {Object.entries(phases).map(([id]) => (
                <option key={id}>{id}</option>
              ))}
            </select>
          ))}
        </div>
        <div className="actions spread small muted" style={{ marginTop: 10 }}>
          <span>
            {intervals.length} segments ·{' '}
            {intervals.filter((i) => i.phase === null).length} unlabeled
          </span>
        </div>
        <ul className={styles.legend}>
          {Object.entries(phases).map(([id, phase]) => (
            <li key={id}>
              <i style={{ background: phase.color }} />
              <b>{id}</b>
              {phase.name}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
