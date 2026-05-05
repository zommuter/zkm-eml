# zkm-eml TODO

## Open questions / deferred work

- **Decoration vs inline-photo classification**: distinguish logos/banners from informational inline images. Heuristics to explore: size threshold, repeated cid across senders, alt-text content, URL-tracking domains in HTML. Currently all attachments are treated uniformly.

- **Per-store YAML/JSON config**: replace .env-only configuration with a richer config file at the store level, shared by zkm core and all plugins. Avoids long comma-separated env values.

- **Deleted-mail policy**: currently messages in zkm are kept even if removed from `~/mail`. Need a flag and detection logic for deletions (diff of message-ids between runs). Options: always keep (default), purge spam, archive-only. Applies to entire folders (e.g. Trash auto-emptied by MUA).

- **Drafts**: optional "follow draft updates" mode where a draft's evolving state is tracked. Tricky because Message-ID and content can change with each save. YAGNI for now.

- **`_objects` garbage collection**: when a stripped .eml is purged from the store, its CAS objects may become orphans. Need a `zkm-eml gc` (or `zkm gc` with per-plugin hooks) that walks all stubs and removes unreferenced objects — analogous to `git gc`.

- **v0.2 quote stripping** (from original CLAUDE.md): detect and collapse full-quote blocks. Trigger via `--reprocess` once implemented. Design sketch preserved in CLAUDE.md.

- **SHA-256 git repos**: `git_blob_sha1` uses SHA-1, which is correct for standard repos. If `~/mail` ever migrates to `git --object-format=sha256`, auto-detect via `git rev-parse --show-object-format` and switch to SHA-256.

- **Attachment MIME type refinement**: currently uses `mimetypes.guess_extension` for synthesized filenames. Could use `python-magic` for more accurate typing if the payload bytes are ambiguous.
