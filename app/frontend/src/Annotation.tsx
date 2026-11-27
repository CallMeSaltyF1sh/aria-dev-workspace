import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { IconArrowBackUp, IconArrowForwardUp } from '@tabler/icons-react'
import { api, type Draft, type Interval, type Library } from './api'
import { historyReducer, sameIntervals } from './annotationModel'
import { AnnotationTimeline } from './AnnotationTimeline'
import { AnnotationInspector } from './AnnotationInspector'
import { AnnotationExport } from './AnnotationExport'
import styles from './Annotation.module.css'

export function Annotation({
  draft,
  phases,
  currentMs,
  onSeek,
  onDirty,
  registerSave,
  registerAdd,
}: {
  draft: Draft
  phases: Library['phases']
  currentMs?: number
  onSeek?: (ms: number) => void
  onDirty: (dirty: boolean) => void
  registerSave: (save: () => Promise<boolean>) => void
  registerAdd: (add: (atMs: number) => void) => void
}) {
  const [history, dispatch] = useReducer(historyReducer, {
    past: [],
    present: draft.intervals,
    future: [],
  })
  const intervals = history.present
  const canUndo = history.past.length > 0
  const canRedo = history.future.length > 0
  const client = useQueryClient()
  const [saved, setSaved] = useState(draft)
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [activeSegment, setActiveSegment] = useState(0)
  const operation = useRef(false)
  const busy = saving || restoring
  const disabled = draft.source_changed || busy
  const dirty = !sameIntervals(intervals, saved.intervals)
  const currentIndex = Math.min(
    activeSegment,
    Math.max(0, intervals.length - 1),
  )
  const currentSegment = intervals[currentIndex]
  const selectedBoundary =
    selected !== null && intervals[selected] && intervals[selected + 1]
      ? intervals[selected]
      : null

  useEffect(() => onDirty(dirty), [dirty, onDirty])

  useEffect(() => {
    const clear = (event: PointerEvent) => {
      const target = event.target as HTMLElement
      if (
        !target.closest(
          '[aria-label^="Split point"],[data-keep-split],[role="dialog"]',
        )
      )
        setSelected(null)
    }
    document.addEventListener('pointerdown', clear)
    return () => document.removeEventListener('pointerdown', clear)
  }, [])

  const removeBoundary = useCallback(
    (index: number) => {
      dispatch({ type: 'remove', index })
      setSelected(null)
      setActiveSegment((prev) =>
        prev > index
          ? prev - 1
          : Math.min(prev, Math.max(0, intervals.length - 2)),
      )
    },
    [intervals.length],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (disabled) return
      const target = event.target as HTMLElement | null
      if (
        target?.closest(
          'input,textarea,select,[contenteditable="true"],[role="dialog"]',
        )
      )
        return
      if ((event.metaKey || event.ctrlKey) && !event.altKey) {
        const key = event.key.toLowerCase()
        if (key === 'z' && !event.shiftKey) {
          event.preventDefault()
          setSelected(null)
          dispatch({ type: 'undo' })
          return
        }
        if ((key === 'z' && event.shiftKey) || (event.ctrlKey && key === 'y')) {
          event.preventDefault()
          setSelected(null)
          dispatch({ type: 'redo' })
          return
        }
        return
      }
      if (event.altKey) return

      if (event.key === 'Escape' && selected !== null) {
        event.preventDefault()
        setSelected(null)
        return
      }

      if (selected !== null && intervals[selected] && intervals[selected + 1]) {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          const nextAt =
            intervals[selected].end_ms +
            (event.key === 'ArrowLeft' ? -100 : 100)
          dispatch({ type: 'move', index: selected, at: nextAt })
          onSeek?.(nextAt)
          return
        }
        if (event.key === 'Delete' || event.key === 'Backspace') {
          event.preventDefault()
          removeBoundary(selected)
          return
        }
      }

      if (event.key === '[') {
        event.preventDefault()
        setActiveSegment(
          Math.max(0, Math.min(currentIndex, intervals.length - 1) - 1),
        )
        return
      }
      if (event.key === ']') {
        event.preventDefault()
        setActiveSegment(Math.min(intervals.length - 1, currentIndex + 1))
        return
      }
      const keyMap: Record<string, Interval['phase']> = {
        '0': 'P0',
        '1': 'P1',
        '2': 'P2',
        '3': 'P3',
        '4': 'P4',
        u: 'unclear',
        U: 'unclear',
      }
      const mapped = keyMap[event.key]
      if (mapped && mapped in phases) {
        event.preventDefault()
        dispatch({ type: 'label', index: currentIndex, phase: mapped })
      } else if (event.key === 'x' || event.key === 'X') {
        event.preventDefault()
        dispatch({ type: 'label', index: currentIndex, phase: null })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    currentIndex,
    disabled,
    intervals,
    onSeek,
    phases,
    removeBoundary,
    selected,
  ])

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
      setActiveSegment(0)
      onDirty(false)
      void client.invalidateQueries({ queryKey: ['library'] })
    } catch (error) {
      setError((error as Error).message)
    } finally {
      operation.current = false
      setRestoring(false)
    }
  }

  const splitAt = (rawMs: number) => {
    if (draft.source_changed || operation.current) return
    const at = Math.round(rawMs / 100) * 100
    const existing = intervals
      .slice(0, -1)
      .findIndex((item) => item.end_ms === at)
    if (existing >= 0) {
      setSelected(existing)
      setActiveSegment(existing + 1)
      return
    }
    const index = intervals.findIndex(
      (item) => item.start_ms < at && at < item.end_ms,
    )
    if (index < 0) return
    const item = intervals[index]
    if (
      at - item.start_ms < 100 ||
      (item.end_ms - at < 100 && index < intervals.length - 1)
    )
      return
    dispatch({ type: 'split', at })
    setSelected(index)
    setActiveSegment(index + 1)
  }

  useEffect(() => {
    registerSave(save)
    registerAdd(splitAt)
  }) // Parent navigation always uses the current editor snapshot.

  const labeledCount = intervals.filter((i) => i.phase !== null).length
  const statusText = restoring
    ? 'Restoring…'
    : saving
      ? 'Saving…'
      : dirty
        ? 'Unsaved edits'
        : saved.revision
          ? 'Saved'
          : 'Not started'
  const statusTone =
    restoring || saving
      ? styles.statusBusy
      : dirty
        ? styles.statusDirty
        : saved.revision
          ? styles.statusSaved
          : styles.statusIdle

  return (
    <section className="card">
      <div className={`cardHead ${styles.annotationHead}`}>
        <div className={styles.headLeft}>
          <h2>Annotation</h2>
          <span className={`${styles.statusPill} ${statusTone}`}>
            <i className={styles.statusDot} aria-hidden="true" />
            {statusText}
          </span>
          <span className={styles.progressSummary}>
            {labeledCount}/{intervals.length} labeled
          </span>
        </div>
        <div className="actions">
          <div className={styles.historyGroup}>
            <button
              type="button"
              className={styles.historyBtn}
              aria-label="Undo"
              disabled={disabled || !canUndo}
              onClick={() => {
                setSelected(null)
                dispatch({ type: 'undo' })
              }}
              title="Undo (⌘Z / Ctrl+Z)"
            >
              <IconArrowBackUp size={15} />
            </button>
            <button
              type="button"
              className={styles.historyBtn}
              aria-label="Redo"
              disabled={disabled || !canRedo}
              onClick={() => {
                setSelected(null)
                dispatch({ type: 'redo' })
              }}
              title="Redo (⇧⌘Z / Ctrl+Shift+Z)"
            >
              <IconArrowForwardUp size={15} />
            </button>
          </div>
          <button
            disabled={busy || !dirty}
            onClick={() => void restore()}
            title="Discard edits and restore the latest saved annotation."
          >
            Restore
          </button>
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
            className="primary"
            disabled={disabled || (!dirty && !!saved.revision)}
            onClick={save}
            title="Save annotation (⌘S / Ctrl+S)"
          >
            Save
            <kbd className={`${styles.kbd} ${styles.kbdDark}`}>⌘S</kbd>
          </button>
        </div>
      </div>

      <div className={`cardBody ${styles.annotationBody}`}>
        {draft.source_changed && (
          <p className="error" style={{ margin: '0 0 10px' }}>
            Source changed. Existing annotation requires review before saving.
          </p>
        )}
        {error && (
          <p role="alert" className="error" style={{ margin: '0 0 10px' }}>
            {error}
          </p>
        )}

        <AnnotationTimeline
          durationMs={draft.duration_ms}
          intervals={intervals}
          phases={phases}
          currentIndex={currentIndex}
          selected={selected}
          currentMs={currentMs}
          disabled={disabled}
          onSelectSegment={setActiveSegment}
          onSelectBoundary={setSelected}
          onSplitAt={splitAt}
          onMoveBoundary={(index, at) =>
            dispatch({ type: 'move', index, at, record: false })
          }
          onCommitDrag={(previous) =>
            dispatch({ type: 'commitDrag', previous })
          }
          onSeek={onSeek}
        />

        {currentSegment && (
          <AnnotationInspector
            segment={currentSegment}
            currentIndex={currentIndex}
            totalSegments={intervals.length}
            phases={phases}
            selectedBoundaryMs={selectedBoundary?.end_ms ?? null}
            disabled={disabled}
            onSelectSegment={setActiveSegment}
            onLabel={(phase) =>
              dispatch({ type: 'label', index: currentIndex, phase })
            }
            onDeleteSplit={() => {
              if (selected !== null) removeBoundary(selected)
            }}
            onSeek={onSeek}
          />
        )}
      </div>
    </section>
  )
}
