# Key user journeys for the zkm-eml CLI surface. The plugin has no UI of its own —
# it is driven through the zkm core CLI against a real store + mail dir, which the
# hermetic test suite cannot exercise. All scenarios are therefore @manual: a human
# checklist (~10 min) to run against a scratch store after substantial changes.
#
#   export ZKM_STORE=/tmp/eml-bdd && zkm init
#   (configure source_dir in $ZKM_STORE/zkm-config.yaml to a small test Maildir)

@manual
Feature: Convert mail to searchable markdown

  Scenario: First convert of a Maildir
    Given a store with source_dir pointing at a Maildir containing a few threads
    When I run "zkm convert eml"
    Then mail/messages/YYYY/MM/ contains one .md per message with subject, participants and thread_id frontmatter
    And mail/threads/ contains one index file per thread listing its members
    And originals/mail/ contains a stripped .eml, a .source.json and attachment symlinks per message
    And attachments appear once each under inbox/mail/YYYY/MM/ as symlinks
    And the run is auto-committed to the store's git history

  Scenario: Re-running convert is idempotent
    Given a store where convert has already run
    When I run "zkm convert eml" again without new mail
    Then no new files are created and "git -C $ZKM_STORE status" stays clean

  Scenario: New mail after an mbsync commit uses the fast path
    Given the mail dir is a git repo and the post-commit hook is installed (make install-hook)
    When mbsync fetches new mail and commits
    Then the hook runs convert + index automatically (check journalctl -t zkm-eml-hook)
    And only the new messages are processed (watermark in .zkm-state/zkm-eml.json advanced)

  Scenario: Quoted replies are collapsed, not lost
    Given a thread where the reply fully quotes its parent below an "On ... wrote:" line
    When I open the reply's .md file
    Then the quoted tail is replaced by a single "> *[Quoted from: ...]*" link to the parent
    And the link resolves to the parent .md file
    And the verbatim quote is still recoverable from originals/mail/<stem>.eml

  Scenario: Reprocess after a renderer upgrade
    Given a store with originals kept and existing messages
    When I run "zkm convert eml --reprocess"
    Then message bodies are re-derived from originals with the current renderer
    And no frontmatter written by other plugins (e.g. entities from NER) is lost
    And no data: URI appears in any rendered body

  Scenario: Searching converted mail
    Given convert and "zkm index" have run
    When I run "zkm search <a phrase from a known mail>"
    Then the matching message .md appears in the top results with a snippet
