# Copilot instructions for rssapi

`rssapi` is a Python FastAPI RSS subscription/API service.

## Coding guidance

- Match the existing Python style and naming.
- Keep route changes focused and covered by tests when practical.
- Prefer small, explicit helpers over broad rewrites.
- Preserve existing cache semantics unless the task asks to change them.
- Do not introduce secrets, cookies, tokens, or local `.env` values into code, tests, logs, or documentation.

## Validation

Before proposing a change, run or recommend:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
```

## Review focus

Call out changes that affect upstream service compatibility, rate limits, authentication requirements, notification/webhook schemas, or cache behavior.
