# CLAUDE.md

This file gives Claude Code project context for `rssapi`.

## Project overview

`rssapi` is a Python RSS subscription/API service. It exposes FastAPI routes for multiple upstream sources such as GitHub, Reddit, Twitter/X, YouTube, Telegram, V2EX, NGA, and other feeds.

## Tech stack

- Python 3.10+
- FastAPI / Uvicorn / Hypercorn
- Pydantic settings
- pytest
- Ruff
- uv for dependency management

## Common commands

```bash
uv venv
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
```

Run a focused test while iterating, then run the full test suite before opening a PR.

## Development workflow

- Work from an Issue when possible.
- Create branches from `main` using `<type>/<issue-id>-<short-desc>`.
- Keep changes scoped to the Issue.
- Do not commit generated caches, virtual environments, local `.env` files, or secrets.
- Use Conventional Commit messages.

## Testing notes

- Tests live under `tests/`.
- Some routes depend on upstream network behavior; prefer unit tests or mocked responses when practical.
- Preserve existing cache and settings behavior unless the Issue explicitly changes it.

## Safety and security

- Never print or commit tokens, cookies, passwords, private keys, or production configuration.
- Treat `.env` as local-only.
- Be careful when changing routes that call third-party services; consider rate limits, login requirements, and upstream compatibility.
- Do not bypass CI, PR review, or branch protection.

## Areas requiring extra care

- Authentication/cookie-dependent upstream sources.
- Notification and webhook schemas.
- Cache TTL/maxsize settings and startup behavior.
- Dependencies fetched from GitHub direct references.
