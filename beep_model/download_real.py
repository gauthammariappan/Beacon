"""Download the CyberPower example alarm WAVs used as a held-out check."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "data" / "real"
SOURCES = DEST / "sources.json"


def main() -> None:
    catalog = json.loads(SOURCES.read_text(encoding="utf-8"))
    DEST.mkdir(parents=True, exist_ok=True)
    for item in catalog["files"]:
        path = DEST / item["file"]
        if path.exists() and path.stat().st_size > 1000:
            print(f"have {path.name}")
            continue
        request = urllib.request.Request(
            item["url"],
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": item["page"],
            },
        )
        print(f"get  {item['url']}")
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
        print(f"saved {path.name} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
