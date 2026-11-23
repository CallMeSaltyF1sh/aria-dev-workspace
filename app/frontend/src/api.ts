import type { components } from './generated/api'

export type Interval = components['schemas']['Interval']
export type FrameSettings = components['schemas']['FrameInput']
export type Study = components['schemas']['StudyInput']
export type Asset = components['schemas']['AssetOutput']
export type Draft = components['schemas']['DraftOutput']
export type Frame = components['schemas']['FrameOutput']
export type Group = components['schemas']['GroupOutput']
export type Job = components['schemas']['JobOutput']
export type Library = components['schemas']['LibraryOutput']
export type Deletion = components['schemas']['DeletionOutput']

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
