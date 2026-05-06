#!/usr/bin/env python
"""Backfill per-attachment and per-CAS sidecars for existing originals.

Usage:
    uv run python backfill.py <store_path>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from zkm_eml.originals import backfill_sidecars

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <store_path>", file=sys.stderr)
        sys.exit(1)
    store = Path(sys.argv[1]).expanduser()
    if not store.is_dir():
        print(f"Error: not a directory: {store}", file=sys.stderr)
        sys.exit(1)
    print(f"Backfilling sidecars in {store} …", flush=True)
    att, cas = backfill_sidecars(store)
    print(f"Done: {att} attachment sidecars written, {cas} CAS sidecar entries merged.")
