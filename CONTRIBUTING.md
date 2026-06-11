# Contributing

Thanks for helping improve `rssapi`.

## Workflow

1. Open or pick an Issue that describes the goal, scope, and acceptance criteria.
2. Create a branch from `main` using `<type>/<issue-id>-<short-desc>`, for example `fix/123-cache-ttl`.
3. Keep changes focused on the Issue scope.
4. Run the local checks before opening a PR.
5. Open a PR and fill in the template, including validation evidence and rollback notes.

## Local setup

```bash
uv venv
uv sync --all-groups
```

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
```

Run targeted tests while iterating, then run the full suite before creating a PR.

## Commit messages

Use Conventional Commit format:

```text
<type>: <short summary>
```

Common types include `feat`, `fix`, `docs`, `ci`, `chore`, `refactor`, and `test`.
When a commit relates to an Issue, include `Refs #<issue-id>` in the commit body or PR description. Use `Closes #<issue-id>` in the PR description when the PR should close the Issue after merge.

## Security

Do not commit API keys, tokens, passwords, private keys, cookies, local `.env` files, or production configuration. If you suspect a secret was committed, follow `SECURITY.md` and rotate the secret before publishing details.
