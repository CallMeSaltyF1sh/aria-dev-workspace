# Data Library verification scope

Detailed recording identifiers, annotation counts and timing measurements are retained privately.

The public verification scope covers:

- MP4 indexing, playback, seeking and decoded-frame stepping.
- Timeline editing, save conflicts and reloading saved annotations.
- Whole-recording frame extraction, timestamp mapping, deduplication and cache reuse.
- Pagination, annotation exports and local file-operation safeguards.
- Synthetic test recordings and a simulated VRS provider; real Gen 2 VRS verification remains pending.

Reproducible validation commands are documented in `app/README.md`.
