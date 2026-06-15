# zkm-eml

zkm plugin that converts Maildir trees or `.eml` files (RFC 5322) to markdown in the
knowledge store, with thread modeling, quote-collapse, attachment CAS detach, PGP/auth
provenance, and `--reprocess` support. Compliant with the zkm
[messaging-spec](https://github.com/zommuter/zkm/blob/main/docs/messaging-spec.md).

**Store dirs**: `mail/messages/`, `mail/threads/`, `mail/_objects/`, `originals/mail/`, `inbox/`
**Discovery**: filesystem (repo lives in `zkm/plugins/`, root `convert.py` shim) or
entry-point (`zkm.plugins` group, wheel install). No `zkm plugin add` needed in dev.

## Commands

```bash
uv sync --extra dev            # editable dep on core via ../../ (run inside plugins/zkm-eml)
uv run pytest                  # hermetic suite — tmp stores, synthetic fixtures, no network
uv run pytest -k <expr>        # one test / one roadmap item's done-check
uv run ruff check src/ tests/ convert.py backfill.py   # lint (line-length 100, py311)
ZKM_STORE=/tmp/kb uv run zkm convert eml               # manual run (needs ZKM_BYPASS_DIRTY_CHECK=1 if tree dirty)
```

This repo is its own git repo (gitignored from the zkm parent). The editable
`zkm = { path = "../../" }` dep means the checkout must sit under a zkm core tree
(real `plugins/` dir or a host worktree) for `uv sync` to resolve.

## Relay contract <!-- relay-executor contract v3 -->

This repo is managed by a reviewer/executor relay. Load `/relay executor` before
working on any item, then follow its rules exactly.

## Layout

```
convert.py              # filesystem-discovery shim → re-exports convert/reprocess/scrub
backfill.py             # one-shot CLI: backfill sidecars for pre-sidecar stores
plugin.yaml             # manifest (filesystem discovery) — DUPLICATED at src/zkm_eml/plugin.yaml
Makefile                # install-hook / uninstall-hook (mbsync post-commit auto-trigger)
hooks/post-commit       # zkm convert eml && zkm index --no-embed, logged to journald + file
scripts/generate_corpus.py  # regenerates the committed conformance corpus (see fixtures README)
src/zkm_eml/
├── convert.py          # convert() / reprocess() / scrub() orchestration
├── source.py           # iter_messages() Maildir+.eml walk; iter_messages_since() git fast path
├── parse.py            # stdlib email → ParsedMessage; charset ladder; PGP Tier A+B headers
├── threading.py        # thread_id_for(): sha256(root reference)[:16]
├── render.py           # body selection, markdownify, data-URI detach, γ body sections
├── quote_strip.py      # tail-quote detection + similarity collapse (stdlib difflib)
├── frontmatter.py      # write_message_md() — messaging-spec frontmatter writer
├── thread_index.py     # thread membership scan + mail/threads/ index writer
├── originals.py        # stripped .eml + CAS objects + sidecars + gc + backfill
├── naming.py           # slugify, message_slug, date_shard, unique_path, sanitize_filename
├── state.py            # <store>/.zkm-state/zkm-eml.json — git watermark per source repo
└── fixtures/corpus/    # conformance corpus shipped inside the wheel (zkm test eml)
tests/                  # 12 files; fixtures/ are all SYNTHETIC — never commit real mail
```

## Config (zkm-config.yaml — NOT .env; .env was retired by the M2 migration)

Plugin section keys (bare snake_case, see `plugin.yaml` for defaults):

- `source_dir` — Maildir tree or flat `.eml` dump, default `~/mail`, read-only
- `folders_exclude` — list or comma-string; empty → built-in defaults (Trash/Junk/Spam/Drafts/German variants)
- `keep_originals` (true) — stripped `.eml` + CAS detach; required for accurate quote-strip + reprocess
- `attachment_inbox` (true) — symlink unique attachments into `inbox/mail/YYYY/MM/`
- `quote_strip` (true) — collapse full tail quotes to `> *[Quoted from: …]*`
- `slug_ascii` (false) — NFKD-fold slugs to ASCII
- `deleted_policy` (keep) — keep | log | purge | archive, applied to source-deleted mails (git fast-path runs only)
- `owner_addresses` — reserved for future identity config; **not consumed during convert**
  (direction detection was removed; frontmatter has no `direction` field anymore)
- `limit_recent` — int, newest-N cap (mtime-sorted); read by convert() but **not declared
  in plugin.yaml** (undeclared-key gotcha)

## Output naming (sharded since v0.10+)

```
mail/messages/YYYY/MM/{YYYY-MM-DD-HHMM}-{thread8}-{slug}.md
mail/threads/YYYY/MM/{anchor-date}-{thread8}-{thread-slug}.md   # anchor = earliest member
originals/mail/YYYY/MM/{stem}.eml / {stem}.source.json / {stem}/<attachment symlinks>
mail/_objects/{sha256[:2]}/{sha256[2:]}            # CAS objects + .json producer sidecars
inbox/mail/YYYY/MM/<filename>                      # symlinks for other plugins
```

`{thread8}` = first 8 chars of thread_id; `{slug}` from subject (Re/Aw/Fwd stripped),
falling back to `from-<localpart>`; collisions get `_1`, `_2`, …

## Pipeline facts (per message, in convert())

1. `parse_eml` — stdlib `email` + `policy.default`. Missing Message-ID → synthetic
   sha256-derived ID. Charset ladder: declared(strict) → utf-8(strict) →
   charset-normalizer detect → utf-8/replace; permissive codecs (latin1/cp1252) are
   never implicit fallbacks. `zkm.encoding.post_decode` (ftfy) finishes.
2. Dedup by bare `message_id` against all existing `mail/messages/**/*.md` (sha256 in
   frontmatter is for the base contract, NOT the dedup key).
3. HTML bodies: inline `data:` URIs are detached to ParsedAttachments
   (`render.detach_html_data_uris`) BEFORE CAS/original writes — prevents base64 blobs
   reaching the embed indexer. **Known gap: reprocess() skips this step (roadmap id:9bf0).**
4. `write_original` — stripped `.eml` (payloads → `X-Zkm-Detached*` stubs; body text
   verbatim), CAS objects + per-object producer sidecars (`zkm.sidecar.merge_producer`),
   per-message symlink dir + per-attachment sidecars, `.source.json` (path / repo commit /
   git blob sha for three retrieval routes).
5. Inbox fan-out via `zkm.inbox.symlink_with_sidecar`; **signature parts
   (`is_signature_part`) never fan out**.
6. `render_body` — plaintext preferred, else markdownify(html.unescape(html)). Quote
   collapse only when parent resolvable (In-Reply-To, then last Reference) and
   similarity ≥ 0.90; interleaved replies untouched; idempotent via marker guard.
7. `split_body_sections` — conservative salutation/signature detection (EN+DE) →
   `salutation_block` / `signature_block` frontmatter (γ-schema scopes).
8. `write_message_md` — **overwrites the whole frontmatter**; keys it does not produce
   (e.g. amender-written `entities[]`) are lost on rewrite. Known reprocess bug,
   roadmap id:9255.

## PGP / auth provenance (PGP2, v0.14.0)

- Tier A: `signed: pgp-mime | smime` from `multipart/signed` protocol param, falling
  back to signature leaf content-type. Signature leaves are CAS-preserved but excluded
  from inbox.
- Tier B: `auth_results:` list parsed from `Authentication-Results`,
  `ARC-Authentication-Results` (with `instance`), `DKIM-Signature` (domain/selector/
  algorithm), and Proton `X-Pm-*` headers. Records are **provenance-named**
  (`source:`, `verified_by:`) — NEVER emit a bare `verified:` claim; the plugin reports
  what headers said, it does not itself verify signatures.

## Incremental enumeration + deletions

- Watermark: `<store>/.zkm-state/zkm-eml.json` keyed by resolved source-repo path,
  stores last processed HEAD. When source is a git repo and the watermark is an
  ancestor of HEAD, only `git diff --name-only` + `git status` paths are enumerated
  (`iter_messages_since`); otherwise full walk. Dedup stays authoritative.
- `deleted_policy` runs only on fast-path runs: maps deleted blobs (git diff
  `--diff-filter=D`) to `.md` files via `source_blob` frontmatter.
- SHA-256 object-format repos are handled (`detect_git_object_format`).

## scrub() / gc / backfill

- `scrub()` (via `zkm scrub eml`) removes NER entity garbage (base64 fragments,
  HTML-entity artefacts) from `entities[]`; dry-run by default.
- `originals.gc_mail_objects` — orphaned CAS objects (all producer messages gone,
  no inbox symlink) — dry-run by default.
- `backfill.py <store>` — one-shot sidecar backfill for stores created before sidecars.

## Tests

- All fixtures synthetic — **never commit real email**. Corpus fixtures
  (`tests/fixtures/corpus/`, mirrored into `src/zkm_eml/fixtures/corpus/` for the
  wheel) are committed; regen via `scripts/generate_corpus.py` — do not hand-edit.
- `tests/conftest.py` provides the `store` fixture (tmp store, `backend="none"`).
- Done-checks for relay items: `uv run pytest -k <id-expr>` per ROADMAP.md.

## Gotchas (hard-won; do not rediscover)

- **plugin.yaml exists TWICE** (root for filesystem discovery, `src/zkm_eml/` for the
  wheel) and both carry their own `version:` — they have drifted from pyproject before
  (roadmap id:7674). `pyproject.toml` + git tag are canonical. The two files also
  differ intentionally in `conformance.config.source_dir` (paths are relative to their
  own location).
- **`frontmatter.PLUGIN_VERSION` is a third hardcoded version literal.**
- **Stripped `.eml` keeps body text verbatim** — including any inline `data:` URIs in
  the HTML part. That is the round-trip guarantee, not a bug; the markdown body is the
  only lossy surface.
- **`write_message_md` rewrites frontmatter wholesale** — adding a key for one path
  (convert) silently drops it on the other (reprocess) unless threaded through both.
- **Maildir `tmp/` is always pruned**, as are dotdirs, `.git`, `.notmuch`, `.snapshots`.
- **`git add` scoping, dirty-tree guard, run guard (exit 75)** — see core
  `zkm/CLAUDE.md`; they all apply when running via `zkm convert eml`.
- Heavy imports (`frontmatter`, `subprocess` users) are deferred inside functions in
  convert.py — keep that pattern.

## Versioning

Loose-0.x bump-and-tag (see core CLAUDE.md): every pyproject `version` change is
tagged `vX.Y.Z` in the same commit. plugin.yaml (both copies) and
`frontmatter.PLUGIN_VERSION` must be bumped in the same commit (guard test:
`tests/test_version_sync.py`).
