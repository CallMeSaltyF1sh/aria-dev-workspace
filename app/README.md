# Dev Workspace — local Data Library

The first working module manages local MP4/VRS recordings, timeline annotations and manually generated full-video frame sets. Prompt Library, VLM Tasks and Evaluation currently show placeholders; no model requests are sent.

For a new machine, follow the [root README](../README.md) first. It covers installation, project directories, where recordings belong, generated data locations, backups and annotation sharing. The startup commands below assume the local dependencies have already been installed.

## Start on this Mac

The dependencies are installed. From the project root:

```sh
python3 scripts/dev_workspace.py
```

Open <http://127.0.0.1:5173>. Stop both services with Ctrl+C. If these ports are already running, use the existing page or stop those services first. Only loopback addresses are used.

For the built interface, without Vite:

```sh
fnm exec --using 24 npm run build --prefix app/frontend
python3 scripts/dev_workspace.py --production
```

Open <http://127.0.0.1:8000>. Rebuild and restart after changing the frontend.

## Recreate the environment

Requirements: Python 3.12, Node 24, FFmpeg/ffprobe. On this Mac, Python/FFmpeg are installed through Homebrew and Node through fnm.

```sh
python3.12 -m venv app/backend/.venv
app/backend/.venv/bin/python -m pip install -r app/backend/requirements.lock
fnm install 24
fnm exec --using 24 npm ci --prefix app/frontend
```

The backend environment is separate from the existing research environment under `work/`. Project Aria Tools is pinned to 2.3.0. The lock file includes its transitive dependencies and development checks. SQLite migrations run at service startup. Run one backend process; this version uses an in-process media queue and local file lock.

## Data locations

| Location | Contents |
| --- | --- |
| `data/` | Original MP4/VRS recordings and user-created folders. Imports copy files here. Confirmed deletions remove these actual files. |
| `workspace/app.db` | Stable asset IDs, file hashes, study metadata and durable job statuses. |
| `workspace/annotations/<asset_id>/draft.json` | Saved human annotation. Unsaved edits remain only in the open editor. |
| `workspace/frames/<asset_id>/<group_id>/` | JPEG frames plus `manifest.json`, generated only when requested. |
| `workspace/previews/<asset_id>/<source_hash>/` | Browser playback proxies and VRS timestamp mapping. |
| `workspace/migrations/pilot-csv-review.json` | Reviewable proposal for importing the original pilot labels. |

Back up `data/` **and** `workspace/` together. The database preserves IDs used by annotations and frame groups. Frames can be listed again from their manifests; rebuilding a deleted database does not recover the original asset IDs automatically. Keys, recordings, derived data, test outputs and local environments are excluded from Git.

## Main workflow

1. Data Library scans `data/` on entry. Use **Scan data/** after external changes. Scanning does not generate frames.
2. Choose a folder, search or filter, and open a recording. Previous/next follows that filtered list; returning preserves the list context.
3. In **Video & Annotation**, seek to a time and choose **Add split point**, or click the annotation axis. Drag in 0.1-second steps. Arrow keys move a focused boundary; Delete/Backspace removes it. Click elsewhere to deselect.
4. Choose a phase for each interval, then **Save**. Drafts may contain unclassified intervals. **Restore** discards edits and reloads the latest saved annotation, or resets to one unlabeled interval without split points if none was saved. It does not write to disk; a loading failure keeps current edits. A final short interval retains the true recording end. Deleting a boundary retains equal neighboring labels and clears unequal ones.
5. **Metadata** stores anonymous participant, trial, garment, condition, split and overlay status. These are descriptive fields; the app does not enforce participant-level data partitioning yet.
6. **Frames & QC** prepares the entire recording at a fixed 0.1-second interval. Click **Generate frames** to start; no target time, frame count or spacing inputs are required. Progress is persisted, and results are shown 24 images per page. Identical source/configuration reuses an intact cache. Frames are never generated just by opening the page.

Playback speed supports 0.5/0.75/1/1.25/1.5/2×. The left/right controls move one **decoded frame**, rather than one second. Full-video frame sets sample `0, 100, 200, …` milliseconds strictly before the recording end. Each request selects the nearest original decoded frame, with an earlier-frame tie break. Duplicate selections produce one JPEG and retain all corresponding `requested_times_ms` in the manifest. Actual timestamps, original frame index, dimensions, source hash, extraction version and settings remain traceable. MP4 is decoded in a single pass; VRS uses DEVICE_TIME and one provider per extraction. Generating frames does not send them to a model. Later Prompt tests and VLM Tasks select their prediction times and context from this cache.

Imports reject existing names. Select **Skip existing filenames** for a batch or change an incoming single-file name. Equal content under a different name requires **Keep duplicate content**. Deletion previews list real files and retained references; active processing blocks deletion. Deleting a source preserves its missing entry, saved annotation and frame history. Interrupted jobs are shown after a service restart; run the same action again to retry.

## Existing pilot annotations

Optional legacy annotation CSVs are supplied separately. Review interval endpoints against each recording duration before approving any migration. No study annotations are included in this repository.

To regenerate the review with the backend initialized:

```sh
PYTHONPATH=app/backend app/backend/.venv/bin/python -m devworkspace.migrate_csv \
  path/to/annotations.csv
```

After the reviewer approves the preview, apply its printed checksum:

```sh
PYTHONPATH=app/backend app/backend/.venv/bin/python -m devworkspace.migrate_csv \
  path/to/annotations.csv \
  --apply-approved REVIEW_CHECKSUM
```

The importer refuses a changed review, changed CSV, changed recording or newer draft. It writes new draft JSONs and leaves the original CSV intact. An interrupted multi-asset import can be reviewed again; it is not a cross-file transaction.

## Export annotations

- In **Annotation**, save changes and choose **Export** → **Export CSV** or **Export JSON**. Export is disabled for unsaved edits and before the first save.
- In **Data Library**, **Export annotations** lists every eligible recording in **all folders**, independent of search and filters, all selected by default. Untick recordings to leave them out; the selected ones are exported as one combined file. The dialog shows recording, segment and unlabeled counts for the selection.
- A recording is included only when its saved draft contains at least one valid phase (`P0`–`P4` or `unclear`). Saved drafts containing only unclassified intervals are excluded. Partially labeled recordings retain every interval: JSON uses `null`, CSV uses an empty phase cell. Unclassified does not become P0 or unclear.
- Export reads a consistent snapshot of the latest saved drafts and never updates them. Missing or changed source recordings remain exportable as historical annotations, with explicit `source_status` flags and preview counts. The exported hash and duration always belong to the saved annotation's source.
- JSON uses export schema v1, includes phase definitions, counts and a `records` array. Each record contains relative `video_id`, local asset ID, source hash, duration, time basis, saved revision, label/schema versions, save time, annotator ID, source status and intervals.
- CSV is UTF-8 with BOM, one interval per row. It repeats recording/provenance fields and includes integer `start_ms`/`end_ms`, three-decimal `start_s`/`end_s`, phase and phase name. Formula-like string cells receive a leading apostrophe for spreadsheet safety; JSON preserves exact strings.
- Source IDs/relative filenames and source hashes help match recordings across computers; local asset UUIDs alone are not portable identities. Export does not include video, frames, study metadata, absolute machine paths or credentials. Filenames and annotation content are not automatically anonymized.
- Generated `annotations_*.csv`/`annotations_*.json`, `exports/`, and the original `workspace/annotations/` are ignored by Git. Share exports separately when needed.
- API: `GET /api/annotations/export-summary[?asset_id=...]`; `GET /api/annotations/exportable` lists eligible recordings; `GET /api/annotations/export?format=csv|json[&asset_id=...]`, where `asset_id` may repeat to export several recordings. Omitting it exports all eligible saved drafts; a selected recording without a labeled draft is rejected.

## Import and VLM recovery (2026-11-26)

Annotation imports preflight every selected recording before changing drafts. Originals are backed up in `workspace/annotation_imports/<transaction_id>/`, with a durable `journal.json`. A failed batch restores original bytes and removes newly created drafts; an uncommitted journal is rolled back at backend startup. Keep these private backups with the rest of workspace. This is a recoverable file transaction for the single-process local service, not a multiuser/distributed transaction.

VLM responses require exactly a valid `label` and a nonblank string `reason` (maximum 2,000 characters). Every target records its output-validation attempts, raw output and errors. Bad output remains `invalid_output`, distinct from the legitimate `unclear` phase. Successful, partial and all-failed runs are persisted and listed as `completed`, `partially_completed` or `failed`; details show errors and expandable response attempts. API request failures do not erase earlier target results. Errors during preparation, before target requests begin, remain processing-job errors.

Configuration is in the repository-root `.env.local`: set `AIHUBMIX_API_KEY`, optionally `VLM_MODELS` and `VLM_API_URL`, then restart the backend. Preserve existing entries when editing; do not overwrite this file with `.env.example` if it already exists. The key-presence indicator does not test credentials or authorize an API call. No real model calls are made by the regression tests.

## Validation commands

```sh
app/backend/.venv/bin/python -m pytest app/backend/tests -q
app/backend/.venv/bin/ruff check app/backend scripts/dev_workspace.py
app/backend/.venv/bin/ruff format --check app/backend scripts/dev_workspace.py
fnm exec --using 24 npm run lint --prefix app/frontend
fnm exec --using 24 npm run format:check --prefix app/frontend
fnm exec --using 24 npm run build --prefix app/frontend
```

With the backend running, regenerate shared request/response types using `npm run types:api --prefix app/frontend` under Node 24, then run the formatter. Tests create isolated temporary workspaces. Browser verification uses a generated test recording, separate from research annotations.

## Verification boundaries

- **Verified with real MP4:** indexing both pilot files, browser playback/seek/step, frame extraction and cache reuse. The full annotation/import/delete flow is also verified with a generated test video.
- **VRS adapter implemented, real recording pending:** RGB stream discovery, DEVICE_TIME reads, frame export, on-demand VFR preview and decoded timestamp validation. A simulated provider test checks irregular timestamp preservation; it does not verify actual Gen 2 recordings. Eye tracking, OptiTrack synchronization and sensor visualizations are outside this first stage.
- The built-in dressing labels are provisional. Saved drafts use `dressing-v1`; immutable evaluation snapshots belong to the later Evaluation module.
- Data Library processing stays local. Starting VLM Run sends its selected frames to the configured API endpoint; it reads AIHUBMIX_API_KEY rather than a Gateway key. There is no multiuser authentication; keep the service bound to loopback.
- MP4 whole-video extraction uses a one-hour subprocess limit; metadata and playback proxy operations retain the five-minute limit. Two jobs can run concurrently. Very long VRS previews may require a later streaming implementation. Batch model sampling belongs to VLM Tasks.

## Whole-video frame cache contract (2026-11-24)

- `POST /api/assets/{id}/frames` takes `{"interval_ms":100,"width":1280}`. The interval is fixed at 100 ms. Old target/count/spacing request fields are rejected.
- `GET /api/assets/{id}/frames` returns compact frame-set summaries, not every frame. `GET /api/assets/{id}/frames/{set_id}?page=1&page_size=24` returns a bounded page (maximum 100). `GET /api/frame-groups` exposes full-video summaries for future selection controls; its URL is retained for compatibility with the earlier plan.
- `workspace/frames/<asset_id>/<set_id>/manifest.json` uses schema version 2 and extraction version 3, with `mode=full_video`, sampling settings, source identity, `sample_count` and an ordered `frames` array. Each frame contains `requested_ms` (first request), `requested_times_ms` (all deduplicated requests), `actual_ms`, original `index`, dimensions and JPEG path; VRS also includes `device_time_ns`.
- `set_id` depends on source hash, RGB stream, time basis, mode, interval, width and extractor version. Partial sets stay in a `.pending` directory and are published atomically only after validation. Incomplete cached sets are rebuilt. Progress is persisted in SQLite via migration 003.
- Legacy target-centered caches remain on disk and remain readable through the API, but the new Frames & QC screen lists full-video sets only. Their old sample-group meaning is not reinterpreted.
- Preparing every 0.1-second frame is distinct from running the VLM at every 0.1 seconds. Quick test will select one full-video set and a test target/context; Tests can select multiple sets with a shared prediction sampling rule. Those model controls belong to their later modules.
