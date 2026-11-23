import type { Asset } from './api'

export function filterAssets(
  assets: Asset[],
  params: URLSearchParams,
): Asset[] {
  const directory = params.get('folder') || ''
  return assets
    .filter(
      (asset) =>
        (!directory || asset.path.startsWith(directory + '/')) &&
        asset.path
          .toLowerCase()
          .includes((params.get('q') || '').toLowerCase()) &&
        (!params.get('format') ||
          asset.path.toLowerCase().endsWith(params.get('format')!)) &&
        (!params.get('media') || asset.info.status === params.get('media')) &&
        (!params.get('annotation') ||
          asset.annotation === params.get('annotation')),
    )
    .sort((a, b) =>
      params.get('sort') === 'duration'
        ? (b.info.duration_ms || 0) - (a.info.duration_ms || 0)
        : a.path.localeCompare(b.path),
    )
}
