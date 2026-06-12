"""README must document the current (M2) config contract, not the retired .env one.

Red tests for roadmap id:d206.
"""

from __future__ import annotations

from pathlib import Path

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def test_readme_no_retired_env_config():
    # roadmap:d206 — the .env / EML_* mechanism was removed in the M2 config
    # migration; documenting it sends users down a dead path.
    for retired in ("EML_SOURCE_DIR", "EML_OWNER_ADDRESSES", "EML_QUOTE_STRIP",
                    "EML_KEEP_ORIGINALS", "EML_ATTACHMENT_INBOX", "EML_FOLDERS_EXCLUDE"):
        assert retired not in README, f"README still documents retired env var {retired}"


def test_readme_documents_zkm_config():
    # roadmap:d206 — config now lives in the store's zkm-config.yaml
    assert "zkm-config.yaml" in README, (
        "README must document plugin config via zkm-config.yaml (see plugin.yaml "
        "config: block for the key list)"
    )
