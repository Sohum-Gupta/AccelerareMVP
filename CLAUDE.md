# AccelerareMVP — guide for Claude Code

This is a Django survey platform built by a solo developer who is learning Django,
Docker and AWS while building. Explain what you are doing and why, in plain
language, before and after each change. Prefer the boring, built-in Django way.

## Read these first

The planning docs in `docs/` are the source of truth. Read them in this order
before doing any work:

1. `docs/05-build-plan.md` — the milestone order and the "Done when" checklists.
   **Milestone 0 is done. Milestone 1 (Accounts) is code-complete and live; its remaining "Done when" boxes
   are live checks (tasks T-3, T-4 and T-5 in `docs/06-backlog.md`). Milestone 2
   (Survey) is done: all PRs merged and deployed (460 tests), and the founder's live checks ticked every
   "Done when" box on 2026-11-12 (PR 11), and the founder closed Milestone 2 the same day.
   Milestone 3 (Organizations) is code-complete and live: PRs 0 to 13 merged and deployed (1,020 tests).
   Its remaining "Done when" boxes are the founder's live checks (task T-16 in `docs/06-backlog.md`; the
   checklist is in the build plan). Milestone 4 (Licences for organizations) is code-complete and live:
   PRs 0 to 5 merged and deployed (1,259 tests). Its remaining "Done when" boxes are the founder's live
   checks (task T-18 in `docs/06-backlog.md`; the checklist is in the build plan). The founder answered
   the choices made while building it, and the payments basics, on 2026-11-13 (the build plan's decision
   log). The licence changes that follow from those answers ("Milestone 4, second part": a licence is set
   aside when an invite or a join code promises one) are code-complete and live (1,315 tests); their two
   live checks are part of T-18. Payments (Milestone 4b, Stripe) are code-complete and deployed: PRs 0
   to 5 (1,547 tests). The founder put Stripe's test keys in Parameter Store on 2026-11-13 and they have
   reached the server, so buying is open on the live site on test keys. Nothing has been run against
   Stripe itself: every test uses a stand-in, and the founder's live checklist (T-22) is the first real
   run. Real keys only when the founder says so. Never let a test reach Stripe (`tests/conftest.py`), and
   never print or commit a key. Milestone 5 (background jobs and the worker, the licence email, the
   audit log, possible duplicates and linking two logins, the match box, the results seam) is
   code-complete and deployed: PRs 0 to 7 (1,786 tests). The server runs a third container, the worker.
   Nobody has tried Milestone 5 by hand on the live site; its remaining "Done when" boxes are the
   founder's live checks (T-24). The interface points the founder raised on the live site (T-19) and
   the "look for duplicates" action (T-25) were built the same day (1,836 tests): a login now lands on
   "My surveys", and the profile is a tidy "Your account" page. Milestone 6 (CSV downloads for an
   organization's admins and for staff, each recorded in the audit log; what an erasure removed, as
   numbers; the numbers on the Django admin's first page; links, search and filters across the admin; a
   written procedure for deletion requests, `docs/08-deletion-requests.md`) is code-complete and
   deployed: PRs 0 to 6 (1,988 tests). Nobody has tried it by hand on the live site; its remaining
   "Done when" boxes are the founder's live checks (T-27). Milestone 7 (hardening and the pilot: error
   pages, a privacy page at `/privacy/`, a limit on guessing join codes, the account number on Sentry's
   reports, a load check, "Send a test error" in the Django admin) is code-complete and deployed: PRs 0
   to 7 (2,054 tests). Nobody has tried it by hand on the live site, no lawyer has read the privacy
   page, and the AWS console items are not done: what remains is the founder's (T-28 and
   `docs/09-pilot-checklist.md`). **Nothing is in progress: Phase 1 is built. Phase 2 (results)
   is planned as Milestones 8 to 13 in the build plan ("Phase 2 — Results", 2026-11-13), but building
   it has not been asked for, so do not start it.** Its plan is written in general words because the
   algorithm is private; the real detail is in the founder's `private/` folder. Merging on green without waiting for a
   review ended with Milestone 7; ask before doing it for anything else. Product choices are asked of
   the founder first.
   `main` is protected on GitHub: every change goes through a pull request whose `test` check has
   passed. The site is built for the US first; India is deferred.**
   Do not build anything from a later milestone than the one in progress.
2. `docs/06-backlog.md` — every open task and parked decision, with full detail in Part 2.
   Add new follow-ups there; remove an item and log the outcome when it is finished.
3. `docs/03-tech-stack.md` — repository layout, conventions, local dev steps.
4. `docs/04-infrastructure.md` — the AWS runbook (what exists, and what is pending).
5. `docs/02-architecture.md` and `docs/01-requirements.md` — background.
6. `docs/08-deletion-requests.md` — how staff handle a request to delete an account (a draft for the
   privacy lawyer). Keep it true whenever erasure changes.
7. `docs/09-pilot-checklist.md` — what only the founder can do before a first customer (the AWS
   console items, the Sentry and uptime checks) and how to bring on the first organization.

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
- The Django admin is the operations hub: nontechnical staff handle about 99% of issues there, so build admin
  tools for anything staff will do repeatedly (plain labels, confirmation pages, a history entry saying who did
  it) and keep AWS console, SSH and GitHub steps to a minimum. Flag any plan step that needs them.
- Never put survey statements, answers or a person's email into a committed file, a test, or an admin history label.
  The real statements are private; tests use `tests/fixtures/questions_sample.json`.
- Never put the real algorithm (which answers count towards what, its names, cut-offs, rules or texts) into a
  committed file, a test, a commit message or a pull request. It will be loaded as private files through the
  Django admin (`docs/06-backlog.md`, D-6); the docs describe it in general words only.
- The privacy page (`templates/privacy.html`) says what the site keeps, who sees it and what an erasure
  removes. A change to any of those changes the page in the same pull request.
- Tests live in `tests/`, run with `uv run pytest` (parallel by default; add `-n 0` to run one at a time).
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
