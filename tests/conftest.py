"""Configure sys.path so tests can import zkm_eml and convert without installation."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root))
