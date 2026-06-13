# Human review queue <!-- budget: 15 min -->

Judgment calls encoded in red tests — confirm or correct the interpretation.
Max ~10 open boxes; the reviewer prunes resolved ones each review turn.

- [ ] tests/test_naming.py::test_slugify_ascii_fold_when_env_set (roadmap:e14b) — the
  test exercises the retired `EML_SLUG_ASCII` env mechanism. Interpretation: rewrite
  to the parameter contract (`slugify(s, slug_ascii=True)`), keeping NFKD-fold
  coverage ("Grüße" → "grue..."). Alternative: delete the test (coverage loss) or
  reintroduce an env override (contradicts "replace means delete").

- [ ] tests/test_docs.py::test_readme_no_retired_env_config (roadmap:d206) — strict
  reading: NO `EML_*` env var may appear anywhere in README, even in a historical
  note. If you want a "migrating from ≤v0.9" appendix mentioning the old names,
  loosen the test to scan only fenced config examples.
