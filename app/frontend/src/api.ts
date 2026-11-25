import type { components } from './generated/api'

export type Interval = components['schemas']['Interval']
export type FrameSettings = components['schemas']['FrameInput']
export type Study = components['schemas']['StudyInput']
export type Asset = components['schemas']['AssetOutput']
export type Draft = components['schemas']['DraftOutput']
export type Frame = components['schemas']['FrameOutput']
export type Group = components['schemas']['FrameSetOutput']
export type FramePage = components['schemas']['FramePageOutput']
export type Job = components['schemas']['JobOutput']
export type Library = components['schemas']['LibraryOutput']
export type Deletion = components['schemas']['DeletionOutput']
export type ExportSummary = components['schemas']['AnnotationExportSummary']
export type ExportItem = components['schemas']['AnnotationExportItem']
export type ImportPreview = components['schemas']['AnnotationImportPreview']
export type ImportResult = components['schemas']['AnnotationImportResult']
export type VlmConfig = components['schemas']['VlmConfigOutput']
export type Prompt = components['schemas']['PromptOutput']
export type PromptSummary = components['schemas']['PromptSummary']
export type PromptPreview = components['schemas']['PromptPreview']
export type PromptInput = components['schemas']['PromptInput']
export type VlmSettings = components['schemas']['VlmInput']
export type VlmRunSummary = components['schemas']['VlmRunSummary']
export type VlmRun = components['schemas']['VlmRunOutput']

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
