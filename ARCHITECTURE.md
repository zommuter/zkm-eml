# zkm-eml architecture — decisions with rationale

Companion to `CLAUDE.md` (facts/commands). This file records WHY, including rejected
alternatives, so future sessions don't re-litigate.

## 1. mbsync + .eml files, not live IMAP

**Decision**: the plugin reads a local Maildir tree / `.eml` dump read-only; fetching
is mbsync's job (or any Maildir producer).
**Rationale**: separates flaky-network/auth concerns from deterministic conversion;
makes the converter testable with committed fixtures; the mail dir being a git repo
enables the watermark fast path and blob-level source provenance.
**Rejected**: `zkm-imap` live fetch — deferred indefinitely; would be a thin fetch
wrapper if ever needed, never merged into this plugin.

## 2. stdlib `email` parser, no external MIME library

**Decision**: `email.message_from_bytes(..., policy=email.policy.default)`.
**Rationale**: zkm's "stdlib > small lib > framework" rule; the stdlib parser with the
modern policy handles RFC 2047/2231, multipart traversal, and defects tolerably.
**Rejected**: `mailparser`, `flanker` — extra deps, no decisive win for our shapes.
Gaps are patched point-wise instead (charset ladder, defensive header re-decode).

## 3. Charset ladder (parse.py)

**Decision**: declared charset strict → utf-8 strict → charset-normalizer detection →
utf-8 with `errors="replace"`; then `zkm.encoding.post_decode` (ftfy) for mojibake.
Permissive codecs (latin-1/cp1252) are honored only when *declared*, and even then
utf-8 is tried first.
**Rationale**: permissive codecs accept every byte string, so using them as implicit
fallbacks masks mis-declared charsets and produces silent mojibake; strict-first makes
mis-declarations detectable.
**Rejected**: chardet-first (slower, less accurate on short bodies); latin-1 blanket
fallback (classic mojibake source).

## 4. Dedup by Message-ID, not sha256

**Decision**: primary dedup key is the bare `message_id` scanned from existing
frontmatter; missing Message-IDs get a synthetic `sha256(first 4 KiB)`-derived ID.
**Rationale**: re-encoding (mbsync flag renames, header reordering by providers)
changes bytes without changing the message; Message-ID survives. `sha256` stays in
frontmatter for the base plugin contract and for `source_blob`-style provenance.
**Rejected**: content-hash dedup (false negatives on byte churn), filename dedup
(Maildir filenames are volatile by design).

## 5. Thread identity = sha256(root reference)[:16]

**Decision**: thread root is `references[0]`, else the message's own ID; thread_id is
a pure function of the root, so it is stable across runs and machines.
**Rationale**: no mutable thread registry to maintain; merging happens implicitly when
the root matches. Thread index files are regenerated from in-memory membership each
run (O(threads), not O(threads × messages)).
**Known limitation**: `In-Reply-To` is currently ignored, so a reply carrying only
`In-Reply-To` (no `References` — some webmail/mobile clients) starts a new thread.
Roadmap id:f583 specs the fallback. Deeper repair (joining via the parent's *stored*
thread_id) is deliberately out of scope until evidence shows broken chains deeper than
one hop matter.
**Rejected**: JWZ threading algorithm — heavy, needs subject heuristics and a global
mutable structure; our git-tracked flat files want a stable pure function.

## 6. Originals: stripped .eml + CAS detach (round-trip guarantee)

**Decision**: store the original with attachment payloads replaced by
`X-Zkm-Detached*` stubs; payloads go to `mail/_objects/<sha256>` (CAS, deduplicated);
per-message symlink dirs + sidecars; `.source.json` records path, source repo commit,
and git blob sha (three independent retrieval routes).
**Rationale**: body text is preserved verbatim (the rendered .md is the only lossy
surface — quote-collapse etc. are always recoverable via `--reprocess`); attachments
dedup across re-forwards and newsletter logos; the store's git history isn't bloated
by repeated binaries.
**Rejected**: storing the full raw .eml (duplicates every attachment), git-annex for
mail originals (annex is for `originals/` user binaries, mail volume is too granular).

## 7. Data-URI detach happens in convert(), before originals/render

**Decision**: `render.detach_html_data_uris` extracts base64 `src="data:..."` images
into synthesized `ParsedAttachment`s (`part_index=-1`) before `write_original` and
`render_body`.
**Rationale**: inline data-URIs otherwise flow verbatim through markdownify into the
.md body, exploding BM25/embed chunks (observed: multi-MB bodies, embed-server 500s —
core item 15b2). Routing them through the normal CAS path gives dedup + sidecars for
free.
**Scope choices**: only quoted, base64 `src=` attributes are matched — CSS
`url(data:...)` and unquoted attributes are left alone until they show up in real
mail. Decode errors leave the URI untouched (fail-open: ugly body beats lost data).
**Known gap**: `reprocess()` does not run the detach step, so reprocessing an HTML
mail leaks the URIs back into the body (red-tested, roadmap id:9bf0).

## 8. Quote-collapse: conservative tail-only, similarity-gated

**Decision**: collapse only a contiguous `>`-block at the very end of the body, only
when one-level-stripped text matches the parent's body at ≥ 0.90
`SequenceMatcher.ratio()`, with single-line EN/DE attribution detection; interleaved
replies are never touched; marker line makes the operation idempotent.
**Rationale**: false collapse destroys rendered information (recoverable only via
reprocess); false keep merely leaves noise. Asymmetric costs → conservative defaults.
**Rejected/deferred**: partial/interleaved segment matching (v0.8 design note in
git history); Outlook-style non-`>`-prefixed quote blocks ("-----Ursprüngliche
Nachricht-----") — collapsing unmarked text is too risky without strong evidence.

## 9. PGP/auth: report provenance, never verdicts (PGP2)

**Decision**: Tier A sets `signed: pgp-mime|smime` from MIME structure; Tier B parses
provider auth headers into `auth_results:` records that always carry `source:` and
`verified_by:`.
**Rationale**: the plugin does not run cryptographic verification, so it must never
emit a bare `verified:` claim — downstream consumers (entity join via fingerprint,
PGP1–4 chain) need to know *who* asserted what. Signature leaves are kept in CAS for
future verification but excluded from inbox fan-out (they are not user documents).
**Rejected**: shipping pgpy verification inside zkm-eml (belongs to the vcard/core
fingerprint chain; key material handling is out of scope for an ingest plugin).

## 10. Git-watermark incremental enumeration

**Decision**: when the source dir is inside a git repo, remember HEAD per source repo
in `<store>/.zkm-state/zkm-eml.json`; next run enumerates only changed/untracked paths
(`git diff` + `git status`), falling back to a full walk whenever the watermark is not
an ancestor of HEAD or git fails. Watermark advances only on successful completion.
**Rationale**: mbsync runs produce a commit per sync (post-commit hook fires the
convert); diff enumeration makes the hook O(new mail) instead of O(mailbox).
Message-ID dedup remains authoritative, so a wrongly-wide enumeration is only a perf
issue, never a correctness one.
**Rejected**: mtime watermarks (mbsync rewrites flags → mtime churn), inotify daemon
(Phase 3 territory).

## 11. Deletions: `deleted_policy`, fast-path only

**Decision**: blobs deleted between watermark and HEAD are mapped to messages via the
`source_blob` frontmatter; policy keep|log|purge|archive, default keep.
**Rationale**: store is an archive — mail deleted at the provider should not silently
vanish from knowledge; purge is opt-in and pairs with `zkm gc`. Restricted to the
git fast path because only there is a reliable deletion signal available.

## 12. Config via zkm-config.yaml (M2), env mechanism retired

**Decision**: all knobs are plugin-config keys (`source_dir`, `quote_strip`, …)
delivered by core from `zkm-config.yaml`; the old `.env` / `EML_*` variables are gone.
`owner_addresses` is accepted-but-unused (reserved for a future my-identities config);
the old `direction:` frontmatter field was dropped with it.
**Gotcha**: `limit_recent` is consumed by convert() but not declared in plugin.yaml.
**Rejected**: keeping a back-compat env shim ("replace means delete" house rule).

## 13. Body γ-sections (salutation/signature) in frontmatter

**Decision**: conservative EN/DE regex detection at render time; blocks are *copied*
into `salutation_block` / `signature_block` frontmatter, body left intact.
**Rationale**: gives NER/γ-schema typed scopes without lossy body mutation (original
"signature stripping" idea was re-scoped to typed extraction, N9g-pre).
False negatives preferred over false positives; signature search window is the last
50 % of the body to dodge `--` lines in quoted content.

## 14. Frontmatter writer is single-producer — and that's a live constraint

`write_message_md` constructs the metadata dict from scratch and overwrites the file.
Under the store-wide amendment contract (md body single-producer, frontmatter
multi-producer), every rewrite path must preserve foreign keys (amender-written
`entities[]`, `source_deleted`, …) and plugin keys computed only on the convert path
(`attachments`). `reprocess()` currently violates this (drops both) — red-tested as
roadmap id:9255. Fix direction: merge previous frontmatter for keys the writer does
not own, rather than teaching every caller to thread every key through.

## 15. Attachment classification is census-first (M1, id:ff0f)

**Decision**: every attachment is labelled `classification: decoration | content |
unknown` (a pure function of single-message metadata in `classify.py`), threaded into
frontmatter `attachments[]` and both sidecars. Inbox fan-out for `decoration` is gated
by `decoration_fanout`, which **defaults to True** — i.e. census mode changes NO
behaviour; it only emits labels so a real mailbox's distribution can be surveyed.
**Rationale**: the house rule "observe before preventing" — misclassification costs are
asymmetric (hiding a real inline photo from inbox fan-out is worse than fanning out a
logo), and the signal base rates (what fraction of inline images are logos vs photos,
how often the same logo CAS object recurs across senders) are unknown until measured.
Shipping the gate defaulted-off would flip behaviour on a guess. The classifier is
deliberately loose: only the two clear cases (small inline cid image → decoration;
non-image or large standalone image → content) are decided; everything mid-size stays
`unknown` so the census bucket that needs human eyes stays visible.
**Deferred to a later threshold-flip turn** (needs census evidence first): cross-sender
CAS-recurrence signal (same logo object seen from N senders ⇒ decoration), alt-text /
tracking-domain heuristics, and any flip of `decoration_fanout` default. See REVIEW_ME.md.
**Rejected**: defaulting `decoration_fanout=False` now (behaviour flip on speculation);
deleting decoration CAS objects (the round-trip/dedup guarantee in §6 is unconditional —
gating only suppresses the inbox *symlink*, never the stored payload).
