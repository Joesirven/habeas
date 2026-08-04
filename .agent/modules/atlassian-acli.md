# module: atlassian-acli

> Gate: Jira / Confluence / Bitbucket / pull requests / merge / any Atlassian product interaction.

## Always use `acli`

Official Atlassian CLI (`acli`, Homebrew `atlassian/acli/acli`). Authenticate once:

```bash
acli auth status
acli jira auth status   # Jira Cloud (habeas-us.atlassian.net)
```

| Do | Do not |
|----|--------|
| `acli jira …` for issues, comments, search, transitions | `gh` (GitHub — wrong host for this repo) |
| `acli` for Confluence / admin when the command exists | Broken Python `bb` / `bitbucket` packages on PATH |
| Prefer `acli` over Atlassian MCP when `acli` covers the task | Invent Bitbucket Cloud-only CLIs against our Server |

## This repo’s Git remote (Bitbucket Server)

- Host: `git.example.internal` (HTTP UI `:7990`, SSH git `:7999`)
- Project / repo: `DSTS` / `data-privacy`
- Integration branch: **`master`** (not `main`)
- Agent branches: `agent/<slug>`

`acli` today ships Cloud product commands (Jira, Confluence, admin). It does **not** yet expose Bitbucket Server pull-request APIs. Until it does:

1. **Push** with git: `git push -u origin HEAD`
2. **Open compare / PR** in Bitbucket UI, or create via Bitbucket Server REST if credentials are available — never `gh pr create`
3. When the user asks to **merge to master**, prefer a clean PR merge in Bitbucket; if they ask for a local merge (matches prior `merge(master): …` history), merge locally and `git push origin master` only after explicit ask

```text
UI compare:
http://git.example.internal:7990/projects/DSTS/repos/data-privacy/compare/commits?sourceBranch=refs/heads/<branch>
```

## Jira examples

```bash
acli jira workitem search --jql 'project = PROJ ORDER BY updated DESC' --limit 10
acli jira workitem view PROJ-000
acli jira workitem comment create --key PROJ-000 --body "Shipped to admin-api-dev."
```
