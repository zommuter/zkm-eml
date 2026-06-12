# Relay log <!-- merge=union; append-only — never edit or reorder past entries -->

## 2026-06-12 21:28 — reviewer (claude-fable-5)

Handoff: CLAUDE.md de-staled (M2 config keys, sharded layout, PGP Tier A+B, dual-plugin.yaml gotcha); ARCHITECTURE.md 14 decisions. ROADMAP 6 ROUTINE + 1 HARD; three NEW verified bugs red-tested: reprocess leaks data: URIs (9bf0), reprocess drops amender frontmatter + attachments[] (9255), thread_id_for ignores In-Reply-To so References-less replies split threads (f583); version drift 0.13/0.14 guard (7674); fresh-clone failures as specs (e14b); README config contract (d206). M1 stays HARD (ff0f, evidence-first); M4 gated YAGNI. 12 red / 175 green; @manual Gherkin; 5 REVIEW_ME.
