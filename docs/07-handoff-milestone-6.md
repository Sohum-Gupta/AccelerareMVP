# Handoff: plan and build Milestone 6

Written on 2026-11-13 at about 3:00pm PST by the Claude session that built Milestones 3 to 5, for a
fresh Claude session on another account. That session cannot see the first one's private notes, so
everything it needs is here or in the docs this file points to. When Milestone 6 is finished, delete
this file in the closing docs PR (ask the founder first: they want to be asked before a file is deleted).

## 1. What you are asked to do

The founder's instruction, word for word (2026-11-13, about 2:25pm PST):

> "you will plan and build milestone 6. do it like milestone 5, build and execute and merge without
> approval. raise any pertinent and necessary decisions to me if needed i will be at my computer"

So, as soon as the founder tells you to start:

1. Check the state (section 3).
2. Read the docs in the order `CLAUDE.md` gives, then the Milestone 5 section of
   `docs/05-build-plan.md` as the model, then its Milestone 6 section.
3. Ask the founder the product decisions (section 6), together, before writing the plan.
4. Write the re-plan of Milestone 6 as its **PR 0** (docs only) and merge it.
5. Build it one small PR at a time (section 7), merging each when its check is green, watching each
   deploy, with a short plain-language summary to the founder after each PR.
6. Finish with a docs PR: what was built, what differs from the plan, the checks run, what was not
   verified, and a live checklist for the founder. Then stop. Milestone 7 has not been asked for.

**Hard stop: nothing merges after 7:00pm PST on 2026-11-13.** The founder shows the application to a
few people at 8pm that day, and every merge to `main` deploys to the live site. Run `date` before each
merge. Do not merge anything risky after about 6:30pm. If you are reading this on a later day, the
deadline is over: ask the founder how they want to go on.

Merging without the founder's review ("merge on green") covers **Milestone 6 only**. Ask before doing
it for anything else.

## 2. Who you are working with

- The founder is a solo developer learning Django, Docker and AWS while building. Explain what you are
  doing and why, in plain language, before and after each change. Short sentences, common words, no
  jargon without a few words of explanation.
- Be honest about what is not verified. Every PR description and every summary says plainly what was
  tested, how, and what nobody has tried. The founder has asked for this more than once.
- The founder decides product questions. Put a real choice to them with the `AskUserQuestion` tool:
  each question must stand on its own, with your recommendation first and marked "(Recommended)".
  Collect a plan's questions and ask them together at the start. Keep to real product choices: they
  tire of small ones ("just do what makes sense"). Small calls you make yourself are listed in the
  plan under "Smaller rules, the builder's calls" so they can be overruled.
- Nontechnical staff run day-to-day operations from the Django admin. Anything staff will do more than
  once gets an admin tool: plain labels, a page that asks first for anything that matters, and a
  history line saying who did it. Flag any step that needs SSH, GitHub or the AWS console.
- When you give the founder a terminal command to run, give the plain command only, with no `#`
  comment on the line: their shell (zsh) breaks on pasted comments.
- Before a check against the live site that could raise a Sentry alert, say so first.
- Ask before deleting any file, dropping the database, or running anything against AWS. There is no
  AWS CLI on this machine; AWS console steps are the founder's.

## 3. Where things stand

Check these first; do not trust this section over what the commands say.

```
date
git status
git log --oneline -3
gh pr list --state all --limit 8
curl -s -o /dev/null -w '%{http_code}\n' https://app.theaccelerare.com/health
curl -s https://app.theaccelerare.com/health/worker
docker compose up -d
uv run pytest -q
```

Expected: branch `main`, clean, at "Close T-19 and T-25, and mark Milestone 6 as next (#98)" or the PR
that added this file; no open PR; `/health` answers 200; `/health/worker` answers `ok`; 1,836 tests
pass in about 20 seconds.

- The live site is `https://app.theaccelerare.com` (one EC2 server, three containers: Caddy, `web`,
  `worker`; RDS PostgreSQL). Every merge to `main` that is not docs-only deploys to it.
- Milestones 0 to 5 and payments (Milestone 4b) are built and deployed. Milestones 3, 4, 4b and 5
  wait only for the founder's own checklists on the live site (backlog T-16, T-18, T-22, T-24).
  **Nobody has tried Milestones 3 to 5 by hand on the live site.** That is the founder's to do; do not
  do it for them and do not tick those boxes.
- Stripe's test keys are on the server, so buying is open on the live site on test keys. No test may
  ever reach Stripe (`tests/conftest.py` enforces it). Never print or commit a key, and never print
  `.env`.
- Amazon SES is still in its sandbox: it delivers only to verified addresses. A second request for
  production access is with AWS (backlog T-4).
- `private/` holds the real survey statements. It is gitignored. **Never read, print or commit it.**
  Tests use `tests/fixtures/questions_sample.json` and made-up data (`example.com`, "Acme"). The
  repository and its Docker image are public.

## 4. The rules that are easy to break

From `CLAUDE.md` and from mistakes already made once:

- Never put a survey statement, an answer, a name or an email address into a committed file, a test, a
  log line, an admin history label or an audit row. People are named by account number there.
- `main` is protected: every change goes through a pull request whose `test` check has passed. Never
  push to `main`.
- Add packages with `uv add` (never `pip install`). Never SQLite. Never edit a committed migration;
  write a new one. Never `docker compose down -v`.
- A new column on a table that has rows must be nullable or have a default, and ideally a
  `db_default`: a deploy migrates first and swaps the code a moment later.
- Apps depend on each other one way only: `accounts <- enterprises <- entitlements <- payments <-
  matching <- responses`, with `funnel`, `jobs`, `audit` and `results` importing no app.
  `tests/test_app_dependencies.py` checks it, and `responses` must stay last in `INSTALLED_APPS`. A
  new `exports` app needs a place in that order (it will read responses, so think where its views
  live; the results job and the `recompute_results` command live in `responses` for the same reason).
- Views are thin. Every write goes through `<app>/services.py`, inside a transaction, and the audit
  row is written in the same transaction (`audit.record(actor, action, target, **facts)`).
- Every PR keeps account erasure (`apps/accounts/erasure.py`) correct for whatever it adds. Other apps
  listen to the `account_erasing` signal.
- Tenant isolation: an organization's admin sees only their own organization, and never answers,
  `took_before`, the match box or a survey taken personally. Write the isolation test before the page
  it protects, and check it by deliberately breaking the scoping. The scoping helpers are in
  `apps/enterprises/scoping.py` (`for_admin`, `for_member`); what an admin may be shown about a member
  comes from `apps/enterprises/shown.py`; the responses pages are in
  `apps/responses/organization_views.py`, which defers the fields in `_NEVER`.
- The site says "organization"; the code says "enterprise".
- If a planning doc and the code disagree, say so and ask rather than picking one silently.

## 5. Milestone 6: what the outline says and what already exists

The Milestone 6 section of `docs/05-build-plan.md` is the October outline: admin polish, CSV export
for staff and for an organization's admins, erasure with an audit record, a staff dashboard. Much has
been built since that it does not know about. Start from the code as it is.

Already built:

- **Erasure.** `apps/accounts/erasure.py`: `plan_erasure`, `erase_account`. It hard-deletes an account
  with no submitted survey and strips the identity of one that has (the survey is kept). An admin page
  asks first and takes a reason. It refuses erasing yourself, the last superuser, and the only admin
  of an organization that still has members. Since Milestone 5 it writes an audit row
  (`account.erased`, with `results_kept`), keeps a shared person when another login is linked to it,
  revokes only the erased login's own unused licences in that case, removes possible duplicates, and
  empties the match box.
- **Audit log.** `apps/audit`: every Django admin history line is copied in automatically, and the
  services record what organization admins do. Superusers read it in the admin.
- **Background jobs.** `apps/jobs`, a `worker` container, `/health/worker`. Handlers are registered
  with `@jobs.job("kind")` in each app's `job_handlers.py`.
- **Possible duplicates** (`apps/matching`), **results** (`apps/results`, empty: there is no
  algorithm), the **Support staff** group (permissions in `apps/responses/signals.py`; made or unmade
  by two actions on the Accounts page of the admin).
- **Admin pages** exist for every model, some polished and some bare. Read each `admin.py` first.

Still to build, as far as the outline goes:

- CSV export of one organization's submitted surveys, for that organization's admins.
- CSV export of everything, for staff, from the Django admin.
- A summary of what an erasure removed (counts, never names) in its audit row, and a written
  procedure for deletion requests: who may ask, the deadline to answer, what is kept and why, and
  that deleted data stays in database backups for 30 days.
- Admin polish: search, filters and links between related things on every model.
- A staff dashboard with counts (accounts, organizations, surveys submitted this week, possible
  duplicates waiting, failed jobs).

A possible PR plan, for you to judge when you re-plan (keep PRs small):

0. `m6-replan`: the re-plan. Docs only.
1. `m6-erasure-summary`: what was removed, as counts, in the audit row and on the page.
2. `m6-export-organization`: the organization admins' CSV. Isolation tests first.
3. `m6-export-staff`: the staff CSV in the Django admin.
4. `m6-admin-polish`: search, filters and links across the admin.
5. `m6-dashboard`: the counts page.
6. `m6-docs-live-checks`: the deletion procedure, docs synced, the founder's live checklist, a backlog
   task for it, and this handoff file removed (ask first).

Things to get right in the exports:

- Stream the file (`StreamingHttpResponse` with a generator over `.iterator()`), so a large export does
  not load into memory.
- The header for answers is `q1..q25` by position, never the statement text.
- A cell that starts with `=`, `+`, `-` or `@` can run as a formula when the file is opened in a
  spreadsheet. A person's name is typed by them, so guard every text cell (prefix a `'`).
- An export is someone taking personal data out of the site: record it in the audit log (who, which
  organization, how many rows), with no names in the record.
- "Tier" is the licence's tier at the time of the export, as the pages show it.

## 6. Decisions to put to the founder first

Ask these together, with `AskUserQuestion`, before writing the plan. Recommendations are mine.

1. **What goes in an organization admin's CSV?** They already see, on the responses page: the member's
   name and email, when the survey was started and submitted, the results level, and "possible
   repeat". Recommended: exactly those columns and nothing more.
2. **Does the staff CSV include the 25 answers?** Superusers can already read answers in the admin;
   Support staff cannot. Recommended: yes, and only superusers may download it.
3. **May Support staff download any export?** Recommended: no.
4. **Is every export written to the audit log?** Recommended: yes.

Do not decide these; they are parked on purpose: what happens when a company asks for all its
members' data to be deleted (D-2, for the privacy lawyer), and a "delete my account" button for
people themselves (D-8).

## 7. How one PR is run

```
git checkout main
git pull --ff-only
git checkout -b m6-short-name
```

Build with tests. Then the local checks, all of which CI also runs:

```
uv run ruff format .
uv run ruff check .
uv run pytest -q
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
```

If a template gained a CSS class, rebuild the styles and commit the result:
`tailwindcss -i assets/tailwind.css -o static/css/app.css --minify`.

Then:

- **Deliberate breaks.** For each code PR, break the new code on purpose, one small change at a time,
  and confirm a test fails. A break no test notices is either a gap (add a test) or a place with a
  second check behind it (say so). Report the numbers in the PR. A small script that applies each
  break, runs the named test files and puts the file back makes this quick; name only the test files
  that ought to catch the break.
- **A real browser** for any new or changed page, at phone width (390) for the site's own pages and
  desktop width for the Django admin. Playwright is not a project dependency: write the script in your
  scratchpad, copy it into `tests/` under a temporary name, run
  `uv run --with playwright pytest tests/<name>.py -n 0 -q -p no:cacheprovider`, and remove the copy
  again. Use `channel="chrome"`, the `live_server` fixture, `@pytest.mark.django_db(transaction=True)`
  and `os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"` at the top. Screenshots go to the scratchpad,
  never the repository. The request-level tests cannot see what a browser sees: on 2026-11-13 a browser
  run found a real fault in the phone field that 1,800 tests had missed.
- **One commit per PR**, with a message that says what and why in plain words, ending with
  `Co-Authored-By: Claude <noreply@anthropic.com>`. The PR description says what it does, the choices
  made, the checks and their numbers, and what was not tried, and ends with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Merge** with `gh pr merge <number> --squash` once `gh pr checks <number>` shows `test` passed.
  Make sure the passing check belongs to the latest commit: `gh pr checks --watch` returns at once if
  CI has not registered yet. Do not use `--delete-branch` while other work is stacked on that branch.
- **Watch the deploy** (about 4 minutes): `gh run list --branch main --workflow Deploy --limit 1`, then
  `gh run watch <id> --exit-status`, then `/health` must answer 200 and `/health/worker` must answer
  `ok`. The deploy ends with a "Worker check". If a deploy fails, fixing it comes before anything else.
  A merge that changes only `docs/**`, `NOTES.md`, `README.md` or `CLAUDE.md` starts no deploy.
- **Wait for one deploy to finish before merging the next code PR.** Build the next PR meanwhile, on a
  branch stacked on the open one. After the merge:
  `git rebase --onto origin/main <old base commit> <branch>`. Commit work in progress before any branch
  juggling.
- **After each PR**, a few plain sentences for the founder: what was built, what it means for a person
  using the site, any call you made, the test count, and anything not verified.
- **Keep the state in the repository.** Update the status line of the build plan's Milestone 6 section
  in every PR, so that a session that loses its memory can find its place from the docs and
  `gh pr list` alone. When something non-obvious is learned, add a dated line to `NOTES.md`.

## 8. Tests: where things are

- Tests are in `tests/`, run in parallel by default (`-n 0` for one at a time). Each test file defines
  its own fixtures; helpers are imported from other test files.
- `tests/orgs.py`: `make_enterprise`, `add_member`, `org_with_admin` (returns the organization and its
  admin's membership), `new_member`, `run_together` (two requests at the same moment, in threads).
- `tests/test_profile.py`: `verified_account(email)` (an account with a verified email and no name).
- `tests/test_matching.py`: `someone(email, phone, name)`, `give(account, tier)`, `take(account,
  membership=None)` (takes and submits a whole survey the real way), `PASSWORD`.
- `tests/payments.py`: a stand-in for Stripe.
- Admin tests make a superuser with `Account.objects.create_superuser(...)` and Support staff with
  `accounts.services.make_support_staff(account)`.
- A test marked `django_db(transaction=True)` empties every table when it ends, including rows a data
  migration made. Such a test must create what it needs (`published_survey()` in
  `tests/test_response_context.py`, `starting_prices()` in `tests/payments.py`).
- `tests/test_tenant_isolation.py` is the slowest file and the most important one: every new page or
  action that belongs to one organization is added to its lists.

## 9. Where to read more

- `CLAUDE.md`: the project's rules and its current status.
- `docs/05-build-plan.md`: every milestone as planned and as built, and the decision log at the end.
  The Milestone 5 section is the model for a re-plan and for the closing docs.
- `docs/06-backlog.md`: every open task and parked decision. Part 1 is for the founder; Part 2 has the
  detail. Add a task for the founder's Milestone 6 live checklist when you write it.
- `docs/03-tech-stack.md` (layout and conventions), `docs/04-infrastructure.md` (the AWS runbook),
  `docs/02-architecture.md` and `docs/01-requirements.md` (background).
- `NOTES.md`: what was learned the hard way, by date. Read the 2026-11-13 entries at least.
