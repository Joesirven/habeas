# module: review-personas

> Gate: before merge of any multi-file change.

Spawn **reviewer** subagents (not the same agent that implemented). Match change type:

| Change touches | Reviewer focus |
|----------------|----------------|
| auth, Identity-Aware Proxy, secrets | security |
| SQL, migrations, queue logic | migration + data correctness |
| matching / suppression outcomes | data quality |
| request or audit payloads | privacy |
| AGENTS.md, README, modules | documentation |
| clients/web | user experience |
| any production path | security + privacy minimum |

Push back with sourced notes in the diff or `tmp/` review file — do not merge on unresolved privacy or security findings.
