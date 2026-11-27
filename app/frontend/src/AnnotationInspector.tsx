import {
  IconChevronLeft,
  IconChevronRight,
  IconPlayerSkipBack,
  IconTrash,
  IconX,
} from '@tabler/icons-react'
import { time, type Interval, type Library } from './api'
import styles from './Annotation.module.css'

export function AnnotationInspector({
  segment,
  currentIndex,
  totalSegments,
  phases,
  selectedBoundaryMs,
  disabled,
  onSelectSegment,
  onLabel,
  onDeleteSplit,
  onSeek,
}: {
  segment: Interval
  currentIndex: number
  totalSegments: number
  phases: Library['phases']
  selectedBoundaryMs: number | null
  disabled: boolean
  onSelectSegment: (index: number) => void
  onLabel: (phase: Interval['phase']) => void
  onDeleteSplit: () => void
  onSeek?: (ms: number) => void
}) {
  return (
    <div className={styles.inspector}>
      <div className={styles.inspectorHeader}>
        <div className={styles.segmentNav}>
          <button
            type="button"
            className={styles.stepBtn}
            aria-label="Previous segment"
            title="Previous segment ([)"
            disabled={currentIndex <= 0}
            onClick={() => onSelectSegment(currentIndex - 1)}
          >
            <IconChevronLeft size={15} />
          </button>
          <span className={styles.segmentBadge}>
            Segment {currentIndex + 1}
            <span className={styles.segmentTotal}>/ {totalSegments}</span>
          </span>
          <button
            type="button"
            className={styles.stepBtn}
            aria-label="Next segment"
            title="Next segment (])"
            disabled={currentIndex >= totalSegments - 1}
            onClick={() => onSelectSegment(currentIndex + 1)}
          >
            <IconChevronRight size={15} />
          </button>
          <span className={styles.segmentRange}>
            {time(segment.start_ms)}–{time(segment.end_ms)}
            <small>
              ({((segment.end_ms - segment.start_ms) / 1000).toFixed(1)}s)
            </small>
          </span>
          {onSeek && (
            <button
              type="button"
              className={styles.seekBtn}
              data-keep-split
              onClick={() => onSeek(segment.start_ms)}
              title="Seek video to start of this segment"
            >
              <IconPlayerSkipBack size={12} />
              Jump to start
            </button>
          )}
          {segment.phase !== null && (
            <button
              type="button"
              className={styles.clearInlineBtn}
              disabled={disabled}
              title="Clear phase back to unlabeled (Shortcut: X)"
              onClick={() => onLabel(null)}
            >
              <IconX size={12} />
              Clear
              <kbd className={styles.kbd}>X</kbd>
            </button>
          )}
        </div>

        <div className={styles.inspectorRight} data-keep-split>
          {selectedBoundaryMs !== null ? (
            <div className={styles.splitContext}>
              <span className={`${styles.splitContextLabel} mono`}>
                Split @ {time(selectedBoundaryMs)}
              </span>
              <span className={styles.splitContextHint}>←/→ 0.1s</span>
              <button
                type="button"
                data-delete-split
                className={`danger ${styles.deleteSplitBtn}`}
                disabled={disabled}
                onClick={onDeleteSplit}
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
        data-keep-split
        role="group"
        aria-label={
          'Phase ' + time(segment.start_ms) + ' to ' + time(segment.end_ms)
        }
      >
        {Object.entries(phases).map(([id, phase]) => {
          const chosen = segment.phase === id
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
              disabled={disabled}
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
              onClick={() => onLabel(id as Interval['phase'])}
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
  )
}
