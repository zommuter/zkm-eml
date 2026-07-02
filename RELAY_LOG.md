# Relay log <!-- merge=union; append-only — never edit or reorder past entries -->

## 2026-06-12 — executor (sonnet)

Worked all 6 ROUTINE items: id:7674 (plugin.yaml version drift 0.13→0.14), id:e14b (fresh-clone test failures: mkdir in test_tmp_always_skipped, rewrite test_slugify_ascii_fold to parameter API), id:f583 (In-Reply-To fallback in thread_id_for + both call sites in convert.py), id:9bf0 (data-URI detach in reprocess path), id:9255 (foreign frontmatter + attachments[] preservation via OWNED_KEYS + extra_meta= on write_message_md), id:d206 (README config section updated to zkm-config.yaml). Full suite: 187 passed, 0 failed. Friction: worktree had a broken .venv because pyproject.toml [tool.uv.sources] uses ../../ relative path that doesn't resolve from ~/.cache/...; worked around by manually installing deps into the worktree .venv using UV_NO_SYNC=1 uv pip install with the absolute zkm path.

## 2026-06-12 21:28 — reviewer (claude-fable-5)

Handoff: CLAUDE.md de-staled (M2 config keys, sharded layout, PGP Tier A+B, dual-plugin.yaml gotcha); ARCHITECTURE.md 14 decisions. ROADMAP 6 ROUTINE + 1 HARD; three NEW verified bugs red-tested: reprocess leaks data: URIs (9bf0), reprocess drops amender frontmatter + attachments[] (9255), thread_id_for ignores In-Reply-To so References-less replies split threads (f583); version drift 0.13/0.14 guard (7674); fresh-clone failures as specs (e14b); README config contract (d206). M1 stays HARD (ff0f, evidence-first); M4 gated YAGNI. 12 red / 175 green; @manual Gherkin; 5 REVIEW_ME.

## 2026-06-12 23:43 — executor (sonnet, relay-loop)

executor: all 6 ROUTINE items shipped (7674 e14b f583 9bf0 9255 d206)

## 2026-06-13 15:01 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review zkm-eml: audited 2cf87ce (docs-only owner decision) clean, 187 tests green, refreshed contract pointer v1→v2, pruned resolved 9255 REVIEW_ME box

## 2026-06-13 23:38 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review 20260613-2304: 1 commit (REVIEW_ME batch-confirm) audited clean, 187 tests green, routine_open=0, pruned 2 confirmed REVIEW_ME boxes

## 2026-06-15 11:24 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

reviewer (claude-opus-4-8, fable-standin, relay-loop): verified REVIEW_ME e14b/d206 confirm; suite 187 green, no gaming; refreshed stale relay-contract pointer v2→v3

## 2026-06-16 10:23 — strong-execute (claude-opus-4-8, fable-standin, relay-loop)

C5 ff0f: M1 attachment classification census mode (decoration|content|unknown in frontmatter+sidecars, decoration_fanout gate default-on), suite 200 green

## 2026-06-16 19:57 — reviewer (claude-opus-4-8, relay-loop)

review 20260616-1957: 1 commit (b2a7e42, REVIEW_ME ff0f human-resolve, docs-only) audited clean; gaming-scan empty; classify.py thresholds (50KB/1KB, lines 32-38) match REVIEW_ME doc + 13 ff0f tests green; suite 200 green; verified ff0f genuinely closed. Fixes: TODO.md e662 summary de-staled (ff0f now closed, not open); contract pointer v3→v4. routine_open=0, no open ROADMAP items. No reverse-handoff additions.

## 2026-06-16 20:55 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review zkm-eml: audited b2a7e42 (ff0f human-resolve, docs-only) clean, suite 200 green, ff0f verified genuine; de-staled TODO e662 + contract pointer v3->v4; routine_open=0

## 2026-06-22 21:26 — maintenance (manual, uv.lock cascade)

uv.lock cascade refresh to zkm 0.16.0 — mechanical version-pin only (id:bae5), audit-exempt class (no code/spec change).

## 2026-06-26 10:02 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review: TODO conformance prose-relocation (id:3441/c095) verified safe — no code/tests touched, all ROADMAP items closed, ledgers conformant

## 2026-06-30 12:20 — reviewer (claude-opus-4-8, fable-standin, relay-loop)

review zkm-eml: verified docs-only TODO ledger-move (Option B); gaming/lint/cross-ledger clean; M1/2527 qualified as design/deferred, no ROADMAP change [id:6755,2527,e662]

## 2026-07-02 00:18 — reviewer (claude-fable-5, relay-loop)

fable recheck (claude-fable-5): standin verdicts upheld (suite 200 green, gaming-scan empty, d462d10 docs-only confirmed); fixed M4 dup-id 2527→6186 + twinned gated M1 remainder id:6755 into ROADMAP deferred (unpromoted-scan now clean), contract pointer v4→v6, pruned 3 resolved REVIEW_ME boxes; routine_open=0 [id:6755,6186,e662,ff0f]

## 2026-07-02 08:46 — reviewer (claude-fable-5, relay-loop)

SPURIOUS dispatch (3rd this run: path-override drop, sig empty, window since relay-ckpt-20260702-0018 EMPTY — root cause already routed:0537/3715); audit clean (gaming-scan/doctor/lint 0 issues), suite green; found+fixed id:a3fd dev-deps→[dependency-groups] (bare uv sync now installs pytest, fresh-clone verify 202 passed), 16-plugin fleet sweep routed:97a9→zkm; routine_open=0 [id:a3fd]
