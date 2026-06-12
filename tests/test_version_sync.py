"""Version metadata must not drift: pyproject.toml + git tag are canonical.

Spec for roadmap id:7674 — both plugin.yaml copies and frontmatter.PLUGIN_VERSION
must report the same version as pyproject.toml.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_root_plugin_yaml_version_matches_pyproject():
    # roadmap:7674
    manifest = yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert str(manifest["version"]) == _pyproject_version(), (
        "plugin.yaml (repo root) version drifted from pyproject.toml — "
        "pyproject + git tag are canonical; sync plugin.yaml in the same commit"
    )


def test_packaged_plugin_yaml_version_matches_pyproject():
    # roadmap:7674
    manifest = yaml.safe_load(
        (REPO_ROOT / "src" / "zkm_eml" / "plugin.yaml").read_text(encoding="utf-8")
    )
    assert str(manifest["version"]) == _pyproject_version(), (
        "src/zkm_eml/plugin.yaml (wheel copy) version drifted from pyproject.toml"
    )


def test_frontmatter_plugin_version_matches_pyproject():
    # roadmap:7674
    from zkm_eml.frontmatter import PLUGIN_VERSION

    assert PLUGIN_VERSION == _pyproject_version(), (
        "frontmatter.PLUGIN_VERSION drifted from pyproject.toml — "
        "either keep the literal in sync or derive it via importlib.metadata"
    )
