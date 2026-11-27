import type { Interval } from './api'

const MAX_HISTORY = 100

export type EditAction =
  | { type: 'label'; index: number; phase: Interval['phase'] }
  | { type: 'split'; at: number }
  | { type: 'move'; index: number; at: number; record?: boolean }
  | { type: 'remove'; index: number }

export type HistoryAction =
  | EditAction
  | { type: 'commitDrag'; previous: Interval[] }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'reset'; intervals: Interval[] }

export type HistoryState = {
  past: Interval[][]
  present: Interval[]
  future: Interval[][]
}

export function sameIntervals(a: Interval[], b: Interval[]): boolean {
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

export function applyEdit(
  intervals: Interval[],
  action: EditAction,
): Interval[] {
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

export function historyReducer(
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

export function computeRulerTicks(durationMs: number) {
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
  const endGuard = Math.max(majorSec * 650, durationMs * 0.09)
  for (let s = 0; s * 1000 < durationMs - endGuard; s += majorSec) {
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
