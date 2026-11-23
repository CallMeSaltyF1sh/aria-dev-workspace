"""Download one coherent Iconstack-listed icon family from Tabler's source."""

from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


NAMES = [
    "arrow-left",
    "arrow-down",
    "arrow-right",
    "chart-bar",
    "checklist",
    "chevron-down",
    "chevron-left",
    "chevron-right",
    "dots",
    "file-text",
    "folder",
    "folder-plus",
    "folders",
    "minus",
    "player-play",
    "plus",
    "refresh",
    "square",
    "square-check",
    "upload",
    "video",
]

ROOT = Path(__file__).parent / "icon-assets" / "tabler"
ROOT.mkdir(parents=True, exist_ok=True)
BASE = "https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline"

for name in NAMES:
    destination = ROOT / f"{name}.svg"
    if destination.exists():
        print(name, "cached")
        continue
    try:
        with urlopen(f"{BASE}/{name}.svg", timeout=15) as response:
            data = response.read()
    except HTTPError as exc:
        print(name, f"HTTP {exc.code}")
        continue
    if b"<svg" not in data or b"</svg>" not in data:
        raise ValueError(f"Invalid SVG for {name}")
    destination.write_bytes(data)
    print(name, len(data))
