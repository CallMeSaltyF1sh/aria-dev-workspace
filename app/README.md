# Dev Workspace — local Data Library

The first working module manages local MP4/VRS recordings, timeline annotations and manually generated frame groups. Prompt Library, VLM Tasks and Evaluation currently show placeholders; no model requests are sent.

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
4. Choose a phase for each interval, then **Save**. Drafts may contain unclassified intervals. A final short interval retains the true recording end. Deleting a boundary retains equal neighboring labels and clears unequal ones.
5. **Metadata** stores anonymous participant, trial, garment, condition, split and overlay status. These are descriptive fields; the app does not enforce participant-level data partitioning yet.
6. **Frames & QC** generates one target group per request. Set target, frame count and spacing. The target is always included; out-of-range context is omitted; duplicate decoded frames are merged. Identical settings reuse an intact cache.

Playback speed supports 0.5/0.75/1/1.25/1.5/2×. The left/right controls move one **decoded frame**, rather than one second. Frame groups retain requested time, actual time, source hash, extraction settings, dimensions and target identity. Even frame counts favor the earlier context side.

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

## Validation

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
- No Gateway key is read in this stage. All study files stay local. There is no multiuser authentication; keep the service bound to loopback.
- Media operations currently have a five-minute subprocess timeout and two workers. Very long VRS previews may require a later streaming implementation. Frame generation creates one group at a time; batch sampling belongs to VLM Tasks.
