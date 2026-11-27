import { useMemo, useRef, useState } from 'react'
import { time, type Interval, type Library } from './api'
import { computeRulerTicks } from './annotationModel'
import styles from './Annotation.module.css'

export function AnnotationTimeline({
  durationMs,
  intervals,
  phases,
  currentIndex,
  selected,
  currentMs,
  disabled,
  onSelectSegment,
  onSelectBoundary,
  onSplitAt,
  onMoveBoundary,
  onCommitDrag,
  onSeek,
}: {
  durationMs: number
  intervals: Interval[]
  phases: Library['phases']
  currentIndex: number
  selected: number | null
  currentMs?: number
  disabled: boolean
  onSelectSegment: (index: number) => void
  onSelectBoundary: (index: number | null) => void
  onSplitAt: (rawMs: number) => void
  onMoveBoundary: (index: number, at: number) => void
  onCommitDrag: (previous: Interval[]) => void
  onSeek?: (ms: number) => void
}) {
  const [hoverMs, setHoverMs] = useState<number | null>(null)
  const axis = useRef<HTMLDivElement>(null)
  const dragging = useRef<{
    index: number
    x: number
    at: number
    previous: Interval[]
  } | null>(null)
  const rulerPointer = useRef<{ x: number; moved: boolean } | null>(null)

  const coordinate = (x: number) => {
    const rect = axis.current!.getBoundingClientRect()
    return Math.max(
      0,
      Math.min(durationMs, ((x - rect.left) / rect.width) * durationMs),
    )
  }

  const ticks = useMemo(() => computeRulerTicks(durationMs), [durationMs])
  const playheadPercent =
    typeof currentMs === 'number' && durationMs > 0
      ? Math.max(0, Math.min(100, (currentMs / durationMs) * 100))
      : null

  const finishDrag = () => {
    const drag = dragging.current
    dragging.current = null
    if (drag) onCommitDrag(drag.previous)
  }

  return (
    <div className={styles.timelineWrap}>
      <div
        className={styles.ruler}
        data-keep-split
        title="Click to place a split point · Drag to scrub video"
        onPointerDown={(event) => {
          if (disabled) return
          rulerPointer.current = { x: event.clientX, moved: false }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          const raw = coordinate(event.clientX)
          const snapped = Math.round(raw / 100) * 100
          setHoverMs(snapped > 0 && snapped < durationMs ? snapped : null)
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
            const snapped = Math.round(coordinate(event.clientX) / 100) * 100
            onSplitAt(snapped)
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
            style={{ left: (ms / durationMs) * 100 + '%' }}
          />
        ))}
        {ticks.major.map((ms, i) => {
          const pct = (ms / durationMs) * 100
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
                ((segment.end_ms - segment.start_ms) / durationMs) * 100
              const showInlineCode =
                segment.phase &&
                (segment.phase === 'unclear' ? share >= 7.5 : share >= 3.8)
              const isActive = intervals.length > 1 && currentIndex === index
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
                    onSelectSegment(index)
                    onSelectBoundary(null)
                  }}
                  onDoubleClick={() => onSeek?.(segment.start_ms)}
                  style={{ width: share + '%' }}
                >
                  <span
                    className={`${styles.clipFace} ${
                      segment.phase ? styles.labeledClip : styles.unlabeledClip
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
            const pct = (segment.end_ms / durationMs) * 100
            const bubbleAlign =
              pct < 8 ? styles.bubbleLeft : pct > 92 ? styles.bubbleRight : ''
            return (
              <button
                key={index}
                type="button"
                aria-label={'Split point ' + time(segment.end_ms)}
                aria-pressed={selected === index}
                className={styles.boundary}
                style={{ left: pct + '%' }}
                disabled={disabled}
                onClick={(event) => {
                  event.stopPropagation()
                  onSelectBoundary(index)
                }}
                onPointerDown={(event) => {
                  event.stopPropagation()
                  onSelectBoundary(index)
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
                      drag.at + coordinate(event.clientX) - coordinate(drag.x)
                    onMoveBoundary(index, nextAt)
                  }
                }}
                onPointerUp={finishDrag}
                onLostPointerCapture={finishDrag}
              >
                <span className={styles.handleGrip} aria-hidden="true" />
                <span className={`${styles.bubble} ${bubbleAlign}`}>
                  {time(segment.end_ms)}
                </span>
              </button>
            )
          })}

          {hoverMs !== null && !disabled && (
            <div
              className={styles.ghostSplit}
              style={{ left: (hoverMs / durationMs) * 100 + '%' }}
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
  )
}
