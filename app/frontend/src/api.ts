import type { components } from './generated/api'

export type Interval = components['schemas']['Interval']
export type FrameSettings = components['schemas']['FrameInput']
export type Study = components['schemas']['StudyInput']
export type Asset = {
  id: string
  path: string
  hash: string
  fingerprint: string
  missing: number
  annotation: string
  info: {
    duration_ms?: number
    width?: number
    height?: number
    fps?: number
    status: string
    error?: string
    codec?: string
    time_basis?: string
  }
  study: Partial<Study>
}
export type Draft = {
  asset_id: string
  revision: number
  source_hash: string
  duration_ms: number
  intervals: Interval[]
  source_changed: boolean
}
export type Frame = {
  file: string
  requested_ms: number
  actual_ms: number
  is_target: boolean
}
export type Group = {
  id: string
  created_at: string
  settings: FrameSettings
  frames: Frame[]
  source_changed: boolean
}
export type Job = {
  id: string
  kind: string
  created_at?: string
  status: string
  error?: string
}
export type Library = {
  assets: Asset[]
  directories: string[]
  phases: Record<string, { name: string; color: string }>
}
export type Deletion = {
  files: string[]
  token: string
  annotations: number
  frame_groups: number
}

export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers:
      body === undefined || body instanceof FormData
        ? undefined
        : { 'Content-Type': 'application/json' },
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
  })
  if (!response.ok) {
    const value = await response
      .json()
      .catch(() => ({ detail: response.statusText }))
    throw new Error(
      typeof value.detail === 'string'
        ? value.detail
        : JSON.stringify(value.detail),
    )
  }
  return response.json()
}
export const time = (ms: number, precision = 1) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(
      2,
      '0',
    )}:${((ms % 60000) / 1000).toFixed(precision).padStart(precision ? 3 + precision : 2, '0')}`
