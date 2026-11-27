import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  IconArrowBackUp,
  IconArrowForwardUp,
  IconChevronLeft,
  IconChevronRight,
  IconPlayerSkipBack,
  IconTrash,
  IconX,
} from '@tabler/icons-react'
import { api, time, type Draft, type Interval, type Library } from './api'
import styles from './Detail.module.css'
import { AnnotationExport } from './AnnotationExport'

const MAX_HISTORY = 100

type EditAction =
  | { type: 'label'; index: number; phase: Interval['phase'] }
  | { type: 'split'; at: number }
  | { type: 'move'; index: number; at: number; record?: boolean }
  | { type: 'remove'; index: number }

type HistoryAction =
  | EditAction
  | { type: 'commitDrag'; previous: Interval[] }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'reset'; intervals: Interval[] }

type HistoryState = {
  past: Interval[][]
  present: Interval[]
  future: Interval[][]
}

function sameIntervals(a: Interval[], b: Interval[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (
      a[i].start_ms !== b[i].start_ms ||
      a[i].end_ms !== b[i].end_ms ||
      a[i].phase !== b[i].phase
    )
      return false
  }
  return true
}

function applyEdit(intervals: Interval[], action: EditAction): Interval[] {
  const next = intervals.map((i) => ({ ...i }))
  if (action.type === 'label') {
    if (next[action.index]) next[action.index].phase = action.phase
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

function historyReducer(
  state: HistoryState,
  action: HistoryAction,
): HistoryState {
  if (action.type === 'reset') {
    return { past: [], present: action.intervals, future: [] }
  }
  if (action.type === 'undo') {
    if (!state.past.length) return state
    const previous = state.past[state.past.length - 1]
    return {
      past: state.past.slice(0, -1),
      present: previous,
      future: [state.present, ...state.future].slice(0, MAX_HISTORY),
    }
  }
  if (action.type === 'redo') {
    if (!state.future.length) return state
    const [next, ...rest] = state.future
    return {
      past: [...state.past, state.present].slice(-MAX_HISTORY),
      present: next,
      future: rest,
    }
  }
  if (action.type === 'commitDrag') {
    if (sameIntervals(action.previous, state.present)) return state
    return {
      past: [...state.past, action.previous].slice(-MAX_HISTORY),
      present: state.present,
      future: [],
    }
  }
  const next = applyEdit(state.present, action)
  if (sameIntervals(state.present, next)) return state
  if (action.type === 'move' && action.record === false) {
    return { ...state, present: next }
  }
  return {
    past: [...state.past, state.present].slice(-MAX_HISTORY),
    present: next,
    future: [],
  }
}

function computeRulerTicks(durationMs: number) {
  if (durationMs <= 0) return { major: [0], minor: [] as number[] }
  const totalSec = durationMs / 1000
  const majorSec =
    totalSec <= 15
      ? 2
      : totalSec <= 45
        ? 5
        : totalSec <= 120
          ? 10
          : totalSec <= 300
            ? 30
            : 60
  const minorSec =
    majorSec === 2
      ? 0.5
      : majorSec === 5
        ? 1
        : majorSec === 10
          ? 2
          : majorSec === 30
            ? 5
            : 10
  const major: number[] = []
  for (let s = 0; s * 1000 < durationMs - majorSec * 350; s += majorSec) {
    major.push(s * 1000)
  }
  major.push(durationMs)
  const minor: number[] = []
  for (let s = minorSec; s * 1000 < durationMs; s += minorSec) {
    const ms = Math.round(s * 1000)
    if (Math.round(s * 10) % Math.round(majorSec * 10) !== 0) {
      minor.push(ms)
    }
  }
  return { major, minor }
}

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
  const [hoverMs, setHoverMs] = useState<number | null>(null)
  const axis = useRef<HTMLDivElement>(null)
  const root = useRef<HTMLElement>(null)
  const dragging = useRef<{
    index: number
    x: number
    at: number
    previous: Interval[]
  } | null>(null)
  const rulerPointer = useRef<{ x: number; moved: boolean } | null>(null)
  const operation = useRef(false)
  const busy = saving || restoring
  const dirty = JSON.stringify(intervals) !== JSON.stringify(saved.intervals)
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
      if (draft.source_changed || busy) return
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
        const nextIdx = Math.max(
          0,
          Math.min(currentIndex, intervals.length - 1) - 1,
        )
        setActiveSegment(nextIdx)
        return
      }
      if (event.key === ']') {
        event.preventDefault()
        const nextIdx = Math.min(intervals.length - 1, currentIndex + 1)
        setActiveSegment(nextIdx)
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
    busy,
    currentIndex,
    draft.source_changed,
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

  const coordinate = (x: number) => {
    const rect = axis.current!.getBoundingClientRect()
    return Math.max(
      0,
      Math.min(
        draft.duration_ms,
        ((x - rect.left) / rect.width) * draft.duration_ms,
      ),
    )
  }

  const unlabeledCount = intervals.filter((i) => i.phase === null).length
  const labeledCount = intervals.length - unlabeledCount
  const playheadPercent =
    typeof currentMs === 'number' && draft.duration_ms > 0
      ? Math.max(0, Math.min(100, (currentMs / draft.duration_ms) * 100))
      : null

  const ticks = useMemo(
    () => computeRulerTicks(draft.duration_ms),
    [draft.duration_ms],
  )

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
    <section className="card" ref={root}>
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
              disabled={busy || draft.source_changed || !canUndo}
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
              disabled={busy || draft.source_changed || !canRedo}
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
            disabled={
              busy || draft.source_changed || (!dirty && !!saved.revision)
            }
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

        <div className={styles.timelineWrap}>
          <div
            className={styles.ruler}
            data-keep-split
            title="Click to place a split point · Drag to scrub video"
            onPointerDown={(event) => {
              if (draft.source_changed || busy) return
              rulerPointer.current = { x: event.clientX, moved: false }
              event.currentTarget.setPointerCapture(event.pointerId)
            }}
            onPointerMove={(event) => {
              const raw = coordinate(event.clientX)
              const snapped = Math.round(raw / 100) * 100
              setHoverMs(
                snapped > 0 && snapped < draft.duration_ms ? snapped : null,
              )
              if (rulerPointer.current) {
                if (
                  !rulerPointer.current.moved &&
                  Math.abs(event.clientX - rulerPointer.current.x) > 4
                ) {
                  rulerPointer.current.moved = true
                }
                if (rulerPointer.current.moved && onSeek) {
                  onSeek(raw)
                }
              }
            }}
            onPointerUp={(event) => {
              const pointer = rulerPointer.current
              rulerPointer.current = null
              if (pointer && !pointer.moved) {
                const snapped =
                  Math.round(coordinate(event.clientX) / 100) * 100
                splitAt(snapped)
                onSeek?.(snapped)
              }
            }}
            onPointerLeave={() => {
              if (!rulerPointer.current) setHoverMs(null)
            }}
            onLostPointerCapture={() => {
              rulerPointer.current = null
              setHoverMs(null)
            }}
          >
            {ticks.minor.map((ms) => (
              <span
                key={'m' + ms}
                className={styles.minorTick}
                style={{ left: (ms / draft.duration_ms) * 100 + '%' }}
              />
            ))}
            {ticks.major.map((ms, i) => {
              const pct = (ms / draft.duration_ms) * 100
              const align =
                i === 0 ? 'start' : i === ticks.major.length - 1 ? 'end' : 'mid'
              return (
                <span
                  key={ms}
                  className={`${styles.majorTick} ${
                    align === 'start'
                      ? styles.tickStart
                      : align === 'end'
                        ? styles.tickEnd
                        : ''
                  }`}
                  style={{ left: pct + '%' }}
                >
                  <span className={styles.tickLabel}>
                    {time(ms, i === ticks.major.length - 1 ? 1 : 0)}
                  </span>
                </span>
              )
            })}
          </div>

          <div className={styles.trackGroove}>
            <div className={styles.trackCanvas} ref={axis}>
              <div
                className={`${styles.segments} ${
                  intervals.length > 1 ? styles.multiSegments : ''
                }`}
                aria-label="Segments by phase"
              >
                {intervals.map((segment, index) => {
                  const share =
                    ((segment.end_ms - segment.start_ms) / draft.duration_ms) *
                    100
                  const showInlineCode =
                    segment.phase &&
                    (segment.phase === 'unclear' ? share >= 7.5 : share >= 3.8)
                  const isActive =
                    intervals.length > 1 && currentIndex === index
                  return (
                    <button
                      key={index}
                      type="button"
                      className={`${styles.segment} ${
                        isActive ? styles.activeSegment : ''
                      }`}
                      aria-label={`Select segment ${index + 1}, ${time(segment.start_ms)} to ${time(segment.end_ms)}`}
                      aria-pressed={isActive}
                      title={
                        `Segment ${index + 1} (${time(segment.start_ms)}–${time(segment.end_ms)}) · ` +
                        (segment.phase
                          ? `${segment.phase}: ${phases[segment.phase].name}`
                          : 'Unlabeled') +
                        ' (Click to select · Double-click to seek to start)'
                      }
                      onClick={() => {
                        setActiveSegment(index)
                        setSelected(null)
                      }}
                      onDoubleClick={() => onSeek?.(segment.start_ms)}
                      style={{ width: share + '%' }}
                    >
                      <span
                        className={`${styles.clipFace} ${
                          segment.phase
                            ? styles.labeledClip
                            : styles.unlabeledClip
                        }`}
                        style={
                          segment.phase
                            ? { backgroundColor: phases[segment.phase].color }
                            : undefined
                        }
                      >
                        {showInlineCode && (
                          <span className={styles.segmentCode}>
                            {segment.phase}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>

              {intervals.slice(0, -1).map((segment, index) => {
                const pct = (segment.end_ms / draft.duration_ms) * 100
                const bubbleAlign =
                  pct < 8
                    ? styles.bubbleLeft
                    : pct > 92
                      ? styles.bubbleRight
                      : ''
                return (
                  <button
                    key={index}
                    type="button"
                    aria-label={'Split point ' + time(segment.end_ms)}
                    aria-pressed={selected === index}
                    className={styles.boundary}
                    style={{ left: pct + '%' }}
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
                        previous: intervals,
                      }
                    }}
                    onPointerMove={(event) => {
                      const drag = dragging.current
                      if (drag?.index === index) {
                        const nextAt =
                          drag.at +
                          coordinate(event.clientX) -
                          coordinate(drag.x)
                        dispatch({
                          type: 'move',
                          index,
                          at: nextAt,
                          record: false,
                        })
                      }
                    }}
                    onPointerUp={() => {
                      const drag = dragging.current
                      dragging.current = null
                      if (drag) {
                        dispatch({
                          type: 'commitDrag',
                          previous: drag.previous,
                        })
                      }
                    }}
                    onLostPointerCapture={() => {
                      const drag = dragging.current
                      dragging.current = null
                      if (drag) {
                        dispatch({
                          type: 'commitDrag',
                          previous: drag.previous,
                        })
                      }
                    }}
                  >
                    <span className={styles.handleGrip} aria-hidden="true" />
                    <span className={`${styles.bubble} ${bubbleAlign}`}>
                      {time(segment.end_ms)}
                    </span>
                  </button>
                )
              })}

              {hoverMs !== null && !draft.source_changed && !busy && (
                <div
                  className={styles.ghostSplit}
                  style={{ left: (hoverMs / draft.duration_ms) * 100 + '%' }}
                  aria-hidden="true"
                >
                  <span className={styles.ghostLabel}>+ {time(hoverMs)}</span>
                </div>
              )}

              {playheadPercent !== null && (
                <div
                  className={styles.playhead}
                  style={{ left: playheadPercent + '%' }}
                  aria-hidden="true"
                >
                  <span className={styles.playheadCap} />
                </div>
              )}
            </div>
          </div>
        </div>

        {currentSegment && (
          <div className={styles.inspector}>
            <div className={styles.inspectorHeader}>
              <div className={styles.segmentNav}>
                <button
                  type="button"
                  className={styles.stepBtn}
                  aria-label="Previous segment"
                  title="Previous segment ([)"
                  disabled={currentIndex <= 0}
                  onClick={() => setActiveSegment(currentIndex - 1)}
                >
                  <IconChevronLeft size={15} />
                </button>
                <span className={styles.segmentBadge}>
                  Segment {currentIndex + 1}
                  <span className={styles.segmentTotal}>
                    / {intervals.length}
                  </span>
                </span>
                <button
                  type="button"
                  className={styles.stepBtn}
                  aria-label="Next segment"
                  title="Next segment (])"
                  disabled={currentIndex >= intervals.length - 1}
                  onClick={() => setActiveSegment(currentIndex + 1)}
                >
                  <IconChevronRight size={15} />
                </button>
                <span className={styles.segmentRange}>
                  {time(currentSegment.start_ms)}–{time(currentSegment.end_ms)}
                  <small>
                    (
                    {(
                      (currentSegment.end_ms - currentSegment.start_ms) /
                      1000
                    ).toFixed(1)}
                    s)
                  </small>
                </span>
                {onSeek && (
                  <button
                    type="button"
                    className={styles.seekBtn}
                    data-keep-split
                    onClick={() => onSeek(currentSegment.start_ms)}
                    title="Seek video to start of this segment"
                  >
                    <IconPlayerSkipBack size={12} />
                    Jump to start
                  </button>
                )}
                {currentSegment.phase !== null && (
                  <button
                    type="button"
                    className={styles.clearInlineBtn}
                    disabled={draft.source_changed || busy}
                    title="Clear phase back to unlabeled (Shortcut: X)"
                    onClick={() =>
                      dispatch({
                        type: 'label',
                        index: currentIndex,
                        phase: null,
                      })
                    }
                  >
                    <IconX size={12} />
                    Clear
                    <kbd className={styles.kbd}>X</kbd>
                  </button>
                )}
              </div>

              <div className={styles.inspectorRight} data-keep-split>
                {selectedBoundary && selected !== null ? (
                  <div className={styles.splitContext}>
                    <span className={`${styles.splitContextLabel} mono`}>
                      Split @ {time(selectedBoundary.end_ms)}
                    </span>
                    <span className={styles.splitContextHint}>←/→ 0.1s</span>
                    <button
                      type="button"
                      data-delete-split
                      className={`danger ${styles.deleteSplitBtn}`}
                      disabled={busy || draft.source_changed}
                      onClick={() => removeBoundary(selected)}
                      title="Delete selected split point (Delete / Backspace)"
                    >
                      <IconTrash size={13} />
                      Delete split
                    </button>
                  </div>
                ) : (
                  <span className={styles.shortcutHint}>
                    <kbd className={styles.kbd}>Space</kbd> play ·{' '}
                    <kbd className={styles.kbd}>,</kbd>
                    <kbd className={styles.kbd}>.</kbd> frame ·{' '}
                    <kbd className={styles.kbd}>[</kbd>
                    <kbd className={styles.kbd}>]</kbd> segment
                  </span>
                )}
              </div>
            </div>

            <div
              className={styles.phasePicker}
              role="group"
              aria-label={
                'Phase ' +
                time(currentSegment.start_ms) +
                ' to ' +
                time(currentSegment.end_ms)
              }
            >
              {Object.entries(phases).map(([id, phase]) => {
                const chosen = currentSegment.phase === id
                const shortcut =
                  id === 'unclear' ? 'U' : id.startsWith('P') ? id.slice(1) : ''
                return (
                  <button
                    key={id}
                    type="button"
                    className={`${styles.phaseCard} ${
                      chosen ? styles.phaseCardChosen : ''
                    }`}
                    aria-pressed={chosen}
                    disabled={draft.source_changed || busy}
                    title={
                      `${id} — ${phase.name}` +
                      (shortcut ? ` (Shortcut: ${shortcut})` : '')
                    }
                    style={
                      chosen
                        ? {
                            backgroundColor: `color-mix(in srgb, ${phase.color} 55%, #ffffff)`,
                          }
                        : undefined
                    }
                    onClick={() =>
                      dispatch({
                        type: 'label',
                        index: currentIndex,
                        phase: id as Interval['phase'],
                      })
                    }
                  >
                    <span
                      className={styles.phaseBar}
                      style={{
                        backgroundColor: `color-mix(in srgb, ${phase.color} 78%, #171717)`,
                      }}
                      aria-hidden="true"
                    />
                    <span className={styles.phaseText}>
                      <b>{id}</b>
                      <span className={styles.phaseDesc}>{phase.name}</span>
                    </span>
                    {shortcut && <kbd className={styles.kbd}>{shortcut}</kbd>}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
