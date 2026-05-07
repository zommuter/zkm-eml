"""Per-plugin persistent state for zkm-eml.

State file: ``<store>/.zkm-state/zkm-eml.json``
Keyed by resolved source-repo path so multiple source repos are tracked
independently. The file is gitignored (add ``.zkm-state/`` to the store's
``.gitignore`` if not already present).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from zkm.atomic import write_atomic

_STATE_FILE = ".zkm-state/zkm-eml.json"


def read_state(store: Path) -> dict[str, dict]:
    """Return the current state dict, or {} if the file is absent / corrupt."""
    path = store / _STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(store: Path, state: dict[str, dict]) -> None:
    """Atomically persist *state* to the state file."""
    path = store / _STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def get_last_commit(store: Path, repo: Path) -> str | None:
    """Return the watermark commit SHA for *repo*, or None if not recorded."""
    return read_state(store).get(str(repo), {}).get("last_commit")


def set_last_commit(store: Path, repo: Path, sha: str) -> None:
    """Record *sha* as the last successfully processed commit for *repo*."""
    state = read_state(store)
    state[str(repo)] = {
        "last_commit": sha,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    write_state(store, state)
