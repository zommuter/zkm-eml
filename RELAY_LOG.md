# Relay log <!-- merge=union; append-only — never edit or reorder past entries -->

## 2026-06-12 — executor (sonnet)

Worked all 6 ROUTINE items: id:7674 (plugin.yaml version drift 0.13→0.14), id:e14b (fresh-clone test failures: mkdir in test_tmp_always_skipped, rewrite test_slugify_ascii_fold to parameter API), id:f583 (In-Reply-To fallback in thread_id_for + both call sites in convert.py), id:9bf0 (data-URI detach in reprocess path), id:9255 (foreign frontmatter + attachments[] preservation via OWNED_KEYS + extra_meta= on write_message_md), id:d206 (README config section updated to zkm-config.yaml). Full suite: 187 passed, 0 failed. Friction: worktree had a broken .venv because pyproject.toml [tool.uv.sources] uses ../../ relative path that doesn't resolve from ~/.cache/...; worked around by manually installing deps into the worktree .venv using UV_NO_SYNC=1 uv pip install with the absolute zkm path.

## 2026-06-12 21:28 — reviewer (claude-fable-5)

Handoff: CLAUDE.md de-staled (M2 config keys, sharded layout, PGP Tier A+B, dual-plugin.yaml gotcha); ARCHITECTURE.md 14 decisions. ROADMAP 6 ROUTINE + 1 HARD; three NEW verified bugs red-tested: reprocess leaks data: URIs (9bf0), reprocess drops amender frontmatter + attachments[] (9255), thread_id_for ignores In-Reply-To so References-less replies split threads (f583); version drift 0.13/0.14 guard (7674); fresh-clone failures as specs (e14b); README config contract (d206). M1 stays HARD (ff0f, evidence-first); M4 gated YAGNI. 12 red / 175 green; @manual Gherkin; 5 REVIEW_ME.

## 2026-06-12 23:43 — executor (sonnet, relay-loop)

executor: all 6 ROUTINE items shipped (7674 e14b f583 9bf0 9255 d206)

## 2026-06-13 15:01 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review zkm-eml: audited 2cf87ce (docs-only owner decision) clean, 187 tests green, refreshed contract pointer v1→v2, pruned resolved 9255 REVIEW_ME box
