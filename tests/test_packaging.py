# roadmap:a3fd
"""Dev tooling must live in [dependency-groups] so a bare `uv sync` installs it.

With dev deps under [project.optional-dependencies], `uv sync` skips them and
`uv run pytest` silently falls through to a system pytest (wrong interpreter,
collection errors). uv auto-installs the `dev` dependency group by default,
which is also the convention used by the zkm parent and sibling plugins.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _load():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_dev_deps_declared_as_dependency_group():  # roadmap:a3fd
    data = _load()
    groups = data.get("dependency-groups", {})
    dev = groups.get("dev", [])
    names = [str(spec).split(">=")[0].split("==")[0].strip() for spec in dev]
    assert "pytest" in names, (
        "pytest must be in [dependency-groups].dev so `uv sync` installs it "
        "and the documented done-check `uv run pytest` works from a fresh clone"
    )
    assert "ruff" in names, "ruff must be in [dependency-groups].dev"


def test_dev_extra_not_duplicated_in_optional_dependencies():  # roadmap:a3fd
    data = _load()
    optional = data.get("project", {}).get("optional-dependencies", {})
    assert "dev" not in optional, (
        "dev tooling must not be split-brained between [dependency-groups] "
        "and [project.optional-dependencies]"
    )
