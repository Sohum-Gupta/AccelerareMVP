# AccelerareMVP — guide for Claude Code

This is a Django survey platform built by a solo developer who is learning Django,
Docker and AWS while building. Explain what you are doing and why, in plain
language, before and after each change. Prefer the boring, built-in Django way.

## Read these first

The planning docs in `docs/` are the source of truth. Read them in this order
before doing any work:

1. `docs/05-build-plan.md` — the milestone order and the "Done when" checklists.
   **Milestone 0 is done. Milestone 1 (Accounts) is code-complete and live (main `2d5d60e`, 2026-10-09);
   its remaining "Done when" boxes are live checks listed under "Open follow-ups". Milestone 2 (Survey)
   is in progress: its section was re-planned on 2026-10-09 (statements private, 1–4 scale, licences) and lists the ten PRs in order; check
   which are merged before starting the next.** Do not build anything from a later milestone than the
   one in progress.
2. `docs/03-tech-stack.md` — repository layout, conventions, local dev steps.
3. `docs/04-infrastructure.md` — the AWS runbook (what exists, and what is pending).
4. `docs/02-architecture.md` and `docs/01-requirements.md` — background.

## Project facts

- Python 3.12, Django 6.1 (note: 6.1 uses the `MAILERS` setting, not `EMAIL_BACKEND`).
- Dependencies managed with `uv`. Add packages with `uv add <pkg>` (or `uv add --dev`
  for test/lint tools). Never `pip install`.
- Settings are split: `config/settings/base.py`, `local.py`, `production.py`.
  Secrets come from environment variables via `django-environ`. Never write a
  real credential into any file that is committed.
- Local database is PostgreSQL 16 in Docker Compose. Never use SQLite.
- Custom user model `accounts.Account` (email login) must exist and be set as
  `AUTH_USER_MODEL` **before the first migration runs**.
- Apps live under `apps/`. Views are thin; all writes go through `<app>/services.py`.
- Tests live in `tests/`, run with `uv run pytest`.
- Lint and format with `uv run ruff check .` and `uv run ruff format .`.

## Commands

```
uv run python manage.py <cmd>      # all Django commands
uv run pytest                      # tests
uv run ruff check . && uv run ruff format --check .
docker compose up -d               # local PostgreSQL
```

## Rules

- One idea per commit, with a message saying what and why. Do not commit `.env`.
- Never edit a migration that has already been committed; write a new one.
- Ask before deleting files, dropping the database, or running anything against AWS.
- When something non-obvious is learned, add a short entry to `NOTES.md`.
- If a planning doc and the code disagree, say so and ask rather than silently
  picking one.
