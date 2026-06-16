# Human review queue <!-- budget: 15 min -->

Judgment calls encoded in red tests — confirm or correct the interpretation.
Max ~10 open boxes; the reviewer prunes resolved ones each review turn.

- [x] tests/test_naming.py::test_slugify_ascii_fold_when_env_set (roadmap:e14b) — the
  test exercises the retired `EML_SLUG_ASCII` env mechanism. Interpretation: rewrite
  to the parameter contract (`slugify(s, slug_ascii=True)`), keeping NFKD-fold
  coverage ("Grüße" → "grue..."). Alternative: delete the test (coverage loss) or
  reintroduce an env override (contradicts "replace means delete"). — confirmed by user 2026-06-15 (review_me batch triage)

- [x] tests/test_docs.py::test_readme_no_retired_env_config (roadmap:d206) — strict
  reading: NO `EML_*` env var may appear anywhere in README, even in a historical
  note. If you want a "migrating from ≤v0.9" appendix mentioning the old names,
  loosen the test to scan only fenced config examples. — confirmed by user 2026-06-15 (review_me batch triage)

- [ ] tests/test_classify.py (roadmap:ff0f) — M1 attachment classification thresholds
  are HEURISTIC, not yet evidence-backed. The shipped interpretation (census mode):
  decoration = small (≤50 KB) inline cid-referenced image OR tracking-pixel-sized
  (≤1 KB) image; content = any non-image part OR a standalone image ≥50 KB; everything
  else (mid-size inline images) = unknown. `decoration_fanout` defaults TRUE so census
  changes no behaviour. Two judgment calls for you: (a) are these byte thresholds
  sane to gather a first distribution, or do you want different cut points before the
  census runs on a real mailbox? (b) the deferred cross-sender CAS-recurrence signal
  (same logo object from N senders ⇒ decoration) and any flip of the fanout default
  are explicitly NOT in this turn — confirm that staging (census now, threshold-flip
  after evidence) matches your intent. Alternative rejected here: defaulting
  decoration_fanout=False now (a behaviour flip on a guess, contra "observe before
  preventing").
