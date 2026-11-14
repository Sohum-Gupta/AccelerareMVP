# Build Plan — Survey Platform

As of 2026-10-05 · Planning Session 5 · Depends on all four earlier docs; open items live in `06-backlog.md` · Milestone 2 and later revised 2026-10-09 · Milestone 2 status synced 2026-10-10 · Milestone 2 live checks recorded and Milestone 2 closed 2026-11-12 · Milestone 3 re-planned 2026-11-12 · Milestone 3 built and status synced 2026-11-13 · Milestone 4 re-planned 2026-11-13 · The founder's answers on Milestone 4's choices and the payments basics recorded 2026-11-13 · Milestone 4b planned and built 2026-11-13 · Milestone 5 re-planned 2026-11-13 · Milestone 6 re-planned and built 2026-11-13 · Milestone 7 re-planned and built 2026-11-13

## How to read this document

This is the order in which to build the MVP, split into eight milestones. Each milestone has the same shape:

- **Goal**: the one sentence that says why this milestone exists.
- **What you build**: the models, views, templates and commands, with file paths matching `03-tech-stack.md`.
- **Technical detail**: the decisions that are easy to get wrong, spelled out.
- **Tests**: what must pass before you move on.
- **Done when**: a checklist you can tick.
- **Why this order / what to understand**: the explanation for a first-time end-to-end developer. These sections are long on purpose; skip them once they're obvious.

Milestones build on each other, so do them in order. Each ends in a deployable state: after any milestone you can push to `main` and the site works, just with fewer features. That property is the single most important habit in this plan.

Time estimates are deliberately absent. You're learning Django, Docker and AWS alongside building; the estimate would be wrong. Instead, each milestone is sized so that a stalled milestone is a signal to ask for help, not to push through alone.

---

## Before the first milestone: how projects differ from products

Most of what you've built so far has been judged by "does it work when I run it." A customer-facing product is judged by what happens when it *doesn't* work, when the data is wrong, when a stranger pokes at it, and when it's been running for six months. Concretely, every feature below is held to these standards. Read this list now; it is the lens for every "Done when" checklist.

1. **Every input is hostile until validated.** A form field can contain anything. A URL parameter can be edited. A request can arrive without the page that normally sends it. Validation happens on the server, every time, regardless of what the browser enforces.
2. **Authorization is checked on every request, not on every page.** "The link isn't shown to them" is not security. Each view asks "is this user allowed to do this to this object" before doing anything.
3. **Data outlives code.** You will change the code hundreds of times; the rows in PostgreSQL persist through all of it. A migration that loses a column loses customer data. A model change needs a migration, and that migration must be safe to run against a database that already has rows in it.
4. **Writes are atomic.** "Create the membership, create the entitlement, decrement the seat pool" must all happen or none happen. Django's `transaction.atomic()` is how; use it around every multi-row write.
5. **Errors are visible to you and invisible to the user.** Users see a calm "something went wrong" page. You see the full traceback in Sentry. Nothing fails silently.
6. **Empty states exist.** A table with zero rows, an enterprise with no members, a user with no responses: each needs a sensible page, not a crash or a blank screen.
7. **Nothing is deleted casually.** Memberships are deactivated, not removed. Responses are immutable after submit. Deletion is one explicit, audited root-admin action.
8. **Secrets are never in the repository.** Not in code, not in commits, not in screenshots.
9. **Every change is small and reversible.** One feature per branch, one idea per commit, tests passing before merge. If a deploy breaks, the previous image is one command away.
10. **Boring is good.** The temptation in a solo project is to try the clever thing. Resist it. Use the Django feature that already exists. Clever code is a liability when you're the only one who has to read it in six months.

---

## Working method

**Branches and commits.** `main` is always deployable. Work on a branch per milestone step (`m1-signup`, `m3-join-code`). Commit whenever something works, with a message that says what and why. Open a pull request to yourself before merging: the diff view catches mistakes that the editor hides, and CI must be green.

**Tests first on the risky parts, tests after on the rest.** Write the test before the code for anything involving permissions, money (seats), or data integrity. For templates and simple views, write the code and then a test that loads the page as each role.

**Run the worker locally always.** Keep `uv run python manage.py run_worker` running in a second terminal from milestone 5 on. If you forget, jobs silently queue up and features look broken: the Django admin's "Background jobs" page will say how many are waiting. `--once` does what is due and stops.

**Keep a `NOTES.md`.** Every time you learn something non-obvious (a Django gotcha, a Docker quirk), write it there. It becomes the onboarding doc for the next developer, who may be you after a long break.

**The Django admin is the operations hub.** The end goal is that nontechnical staff handle about 99% of issues, so every operational task (granting or revoking a licence, looking up an account, erasing one, reading the funnel, loading the survey wording) should be doable from the Django admin with plain-language labels, a confirmation page for anything destructive, and a history entry saying who did it. AWS console use should be minimal and GitHub use as little as possible. When a plan step needs SSH, the AWS console or a code change for something staff will do repeatedly, propose an admin alternative first. Two admin levels exist: superusers see everything; the "Support staff" group (debugging and business-insight staff, which for now are the same people) sees licences, accounts, which questions a response has answered (never the answers) and the funnel. Staff actions that go through a service bypass the admin's automatic history, so they call `log_change` themselves.

**Deploy constantly.** After milestone 0 the deploy is automatic. Merge to `main` daily even when the change is small. A deploy that has not happened for two weeks is a deploy you are afraid of.

---

## Milestone 0 — Foundations and first deploy

**Goal:** an empty Django site is running on AWS over HTTPS, deployed automatically from `main`, with tests and linting in CI.

**What you build**

- The repository layout from `03-tech-stack.md`: `pyproject.toml`, `uv.lock`, `config/settings/{base,local,production}.py`, `manage.py`, `apps/`, `templates/base.html`, `static/css/`.
- `apps/accounts/models.py` with the custom user model `Account(AbstractBaseUser, PermissionsMixin)`: fields `email` (unique, used as `USERNAME_FIELD`), `is_active`, `is_staff`, `created_at`, and a `person` foreign key added in milestone 1. Set `AUTH_USER_MODEL = "accounts.Account"` in `base.py` **before running the first migration**.
- A `/health` view returning `200 OK` with the text `ok`, and `/admin/` enabled.
- `docker-compose.yml` with one `postgres:16` service, a named volume, and a `.env.example` that documents every variable.
- `Dockerfile`: `python:3.12-slim`, install `uv`, copy `pyproject.toml` and `uv.lock`, `uv sync --frozen --no-dev`, copy the app, `collectstatic`, run `gunicorn`.
- `.github/workflows/ci.yml` running `ruff check`, `ruff format --check`, and `pytest` against a PostgreSQL service container on every push and pull request.
- `.github/workflows/deploy.yml` on push to `main`: build the ARM image, push to ghcr.io, SSH to the server, run `deploy.sh`.
- Everything in the infrastructure runbook sections 1–7.

**Technical detail**

- The custom user model is non-negotiable before the first migration. Django's docs say changing it mid-project is "difficult"; in practice it means dropping the database.
- `base.py` reads settings through `django-environ`: `env = environ.Env()`, `DATABASES = {"default": env.db("DATABASE_URL")}`, `SECRET_KEY = env("SECRET_KEY")`. `local.py` sets `DEBUG = True` and `EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"`. `production.py` sets `DEBUG = False`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, and `ALLOWED_HOSTS` from the environment. `DJANGO_SETTINGS_MODULE` chooses between them.
- Caddy terminates TLS and forwards to gunicorn on port 8000. Django must be told it is behind a proxy: `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` and `USE_X_FORWARDED_HOST = True` in production, otherwise `SECURE_SSL_REDIRECT` loops forever.
- Static files: `whitenoise` middleware serves the collected CSS and HTMX from the app container. No S3, no CDN.
- The deploy runs migrations before starting the new containers. Migrations must therefore be backward compatible with the still-running old code for the few seconds of overlap; this is not an issue until you rename or drop a column, at which point the rule is "add the new column in one deploy, migrate data, drop the old column in a later deploy."

**Tests**

- `tests/test_health.py`: `GET /health` returns 200.
- `tests/test_settings.py`: `production.py` imports cleanly with the required environment variables set (catches a missing variable before the server does).

**Done when**

- [x] `uv run pytest` and `uv run ruff check .` pass locally and in CI.
- [x] `https://<domain>/health` returns `ok` with a valid certificate.
- [x] `https://<domain>/admin/` shows the Django login page.
- [x] A superuser created with `createsuperuser` can log into the admin on the server.
- [x] Pushing a trivial change to `main` deploys within a few minutes without you touching the server.
- [x] Sentry shows a deliberately raised exception from the server.
- [x] A billing budget alert exists on the AWS account.

**Why this order / what to understand**

Deploying an empty site first is counter-intuitive when there's nothing to show. The reason: the deployment pipeline is the piece most likely to eat days unexpectedly, because it touches Docker, AWS networking, DNS, TLS, GitHub secrets and SSH all at once. If you build features for a month and then try to deploy, every one of those problems arrives on the same day, tangled with whatever application bug you also have. Doing it first means each later milestone is "write code, push, see it live," and the deploy itself is never the thing you're debugging.

A few concepts worth understanding here rather than copying:

*The settings split.* Django reads one settings module. We have three because the same code runs in three contexts (your laptop, the test runner, the server) with different databases, debug flags, and email backends. `base.py` is what's true everywhere; the other two override. Never put a real credential in any of them; they come from the environment, which is different in each context.

*gunicorn versus runserver.* `manage.py runserver` is a development server: single-threaded, reloads on file change, serves static files, and is explicitly unsafe for production. gunicorn is a production WSGI server that runs several worker processes and does nothing else. Caddy sits in front because gunicorn does not do TLS or static files efficiently.

*Migrations.* When you change a model, `makemigrations` writes a Python file describing the change, and `migrate` applies it. The migration files are code and are committed. The database keeps a table of which migrations have been applied, so the same `migrate` command is safe to run repeatedly. Never edit a migration that has run on the server; write a new one.

*CI.* "Continuous integration" just means a computer runs your tests on every push so you can't forget. The PostgreSQL service container in CI means tests run against the same database engine as production, which matters because SQLite and PostgreSQL disagree on details like JSON fields and case sensitivity.

---

## Milestone 1 — Accounts

**Goal:** a person can register with an email, a phone and a password, verify the email, log in (with the primary or any verified email), log out, reset their password from any verified email, and manage their emails: add, make primary, remove. *Scope widened 2026-10-09; see the decision log.*

**What you build**

- `apps/accounts/models.py`: `Person` (id, created_at, merged_into nullable self-FK), `Account.person` FK (nullable at first, backfilled by a data migration, made required in a later PR), `ContactPoint` (account FK, `kind` choices email/phone, `value_normalised`, `value_display`, `verified_at` nullable, `is_primary`). Three constraints, all `UniqueConstraint`: `(kind, value_normalised)` where `verified_at` is not null; `(account, kind, value_normalised)`; `(account, kind)` where `is_primary`. The manager creates the Person and the primary email ContactPoint for every new account so `createsuperuser` keeps the invariants. *(Done in PR `m1-models`.)*
- `apps/accounts/services.py`: `register(email, phone, country, password) -> Account` (creates Person, Account, two ContactPoints, sends verification), `add_email(account, email)`, `make_primary(account, contact)` (verified emails only; updates `Account.email` in the same transaction), `remove_contact(account, contact)` (refuses the primary and the last email), `change_phone`. All raise `ValidationError` on bad input; `register` raises `EmailInUse` so the sign-up page can answer "check your inbox" either way. `apps/accounts/normalisers.py` holds `normalise_email` and `normalise_phone` (E.164 via the `phonenumbers` library, region from the form's country selector: US, India, UK first, then the full list; a leading `+` overrides it). They live apart from `services.py` because `models.py` needs them and `services.py` needs the models; `services.py` imports them from there. *(Done in PR `m1-register`.)*
- allauth configured for email-only accounts, mandatory verification, and `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`. A signal handler on allauth's `email_confirmed` that sets `ContactPoint.verified_at` for that email. When the address is already verified on another account, the confirmation page says so and offers login or password reset for that account; nothing is linked or merged.
- Templates: `accounts/signup.html`, `login.html`, `password_reset*.html`, `verify_sent.html`, `verify_done.html` (the one-time prompt "add a personal email so you can always get back in", skippable; shown on first login after verification, so it belongs with the profile PR), `profile.html` (lists contact points; add email, resend verification, make primary, remove; change phone).
- `templates/base.html` with Tailwind and HTMX loaded, a responsive nav, and a flash-message area.
- Root admin: register `Person`, `Account`, `ContactPoint` in Django admin with search on email and phone.

**Technical detail**

- Email is normalised by lowercasing and trimming; do not strip Gmail dots or plus-aliases, because the matching rule must be exact. Phone is validated with `phonenumbers` for the chosen country (reject what does not parse as a plausible number) and normalised to E.164 (`+91…`, `+1…`, `+44…`) so the same number typed with spaces or a leading zero matches.
- The login identifier is the primary email **or any verified email** on the account (pulled forward from Phase 3 on 2026-10-09). Unverified non-primary emails never log in: two accounts may hold the same unverified address, so the lookup would be ambiguous. Checked on 2026-10-09: allauth resolves email logins through its own `EmailAddress` table (lowercased comparison) and, with verification `mandatory`, only lets the exact address typed log in if that address is verified. So the services mirror every ContactPoint email into allauth's table, and no custom lookup is needed.
- Password reset: the address typed must be a verified contact point on an account (the primary counts only once verified; decided in PR 5); the link goes only to the typed address and a link-free notice goes to the account's other verified emails when the reset is requested. The page always says "if an account exists, we sent a link". allauth's own form also mails unverified addresses, so `PasswordResetRequestForm` replaces it.
- `Account.email` always equals the primary email ContactPoint. Only services change either, inside one transaction.
- Verification is `mandatory`, so an account cannot log in until its email is verified (decided 2026-10-09; allauth sends a fresh link and shows "check your inbox" instead). The `verified_email_required` decorator on every response view from milestone 2 is a second guard, for accounts made outside the normal flow.
- Password hashing: put `Argon2PasswordHasher` first in `PASSWORD_HASHERS` and install `argon2-cffi`.
- Rate limiting on login and password reset: allauth's `ACCOUNT_RATE_LIMITS` defaults are on. They count in Django's cache, which is a PostgreSQL table (`CACHES` in `base.py`, created by `createcachetable` in `deploy.sh`) so both gunicorn workers share one count.
- Phone is required by the form but there is no verification; `verified_at` stays null for phones in the MVP. The phone input is a flag and dial-code picker (intl-tel-input, vendored, default US) that fills the same `phone` and `country` fields; the profile's change-phone reuses `includes/phone_input.html`.
- Password rules: Django's four validators with a minimum length of 10. Signup and the new-password page show live checklists (`includes/field.html` with `hints=`); the server stays the authority and also catches common and too-similar passwords.

**Tests**

- Register creates one Person, one Account, two ContactPoints; the email one is unverified; a verification email was sent.
- Clicking the verification link sets `verified_at`; a second click is harmless.
- Two accounts cannot both verify the same email (constraint error at the database level; the confirmation page offers login or reset of the existing account). Unverified duplicates across accounts are allowed; the same value twice on one account is not; at most one primary per kind.
- Existing accounts (the production superuser) get a Person and a primary email ContactPoint from the backfill migration.
- Phone `098765 43210` with country India and `+91 98765 43210` normalise to the same value; a US and a UK number normalise correctly; `123` is rejected.
- Login succeeds with the primary email and with a verified second email; fails with an unverified second email.
- Make primary changes `Account.email` and login; removing the primary or the last email is refused.
- A password reset sends a notice to the account's other verified emails.
- Unverified account is redirected away from a view decorated `verified_email_required`.
- Password reset flow end to end (request, email contains link, link sets new password, old password no longer works).

**Done when**

- [ ] A stranger can sign up on the live site, receive the email, verify, log in and log out on a phone. *(Waiting on SES production access; until then only verified addresses receive mail. See `06-backlog.md`.)*
- [ ] Password reset works on the live site, from a second verified email too. *(Needs a second address SES can deliver to; see `06-backlog.md`.)*
- [ ] A user can make a second email primary, log in with it, and remove the old one. *(Same: needs a second deliverable address.)*
- [x] All tests above pass. *(158 passed, ruff and `check --fail-level WARNING` clean, 2026-10-09.)*
- [ ] Root admin can find an account by email or phone in the admin.

**Why this order / what to understand**

Accounts come before the survey because every later feature asks "who is this." Getting identity right now avoids retrofitting `person_id` onto everything later.

*Person versus Account.* This is the design decision that makes repeat-user detection possible. An Account is a login. A Person is the human. Today they're one-to-one; after an auto-link, two Accounts share one Person. Everything that cares about "the human" (entitlements bought individually, the merge feature) points at Person. Everything that cares about "the login" (passwords, memberships, responses) points at Account. Keep that distinction clean and milestone 5 is easy.

*Why contact points are their own table.* It lets an account have any number of emails and phones with a verification date each, and lets a single database constraint say "a verified email belongs to exactly one account." That constraint is the thing that makes auto-linking safe: nobody can claim your email without clicking a link sent to it.

*Why allauth and your own templates.* allauth has its own pages, and they look like allauth. Using its views and functions but your templates gives you its tested flows with your design. The tech stack doc says which URLs to mount; mount only those.

*What verification actually prevents.* Without it, anyone can sign up as `ceo@acme.com`. With it, the account is inert until the real owner clicks. It also makes the email a reliable identity signal for matching.

---

## Milestone 2 — Survey and responses (individual context)

*Re-planned on 2026-10-09 from the founder's questionnaire and licence rules. This section replaces the original one-question-per-page, 1–5, no-paywall plan; the differences are in the decision log.*

**Goal:** a verified individual who holds a licence can read the disclosure, answer the self-report question, answer the 25 statements five to a page with autosave, leave and resume, submit, and see their survey history. A licence is one attempt. Submitted responses are immutable, and the person never sees their answers again after submitting. The statements are private: they are never committed to the public repository and are loaded from a file the founder keeps, through an admin page (PR 9).

**Status (2026-10-10).** Code-complete and deployed. Merged: PR 1 survey models and `load_questions` (#31), PR 2 licences (#32), PR 3 the `Response` model and the two-level admin (#33), PR 3b erasing an account (#34), PR 3c the funnel (#35), PR 4 response services (#37), PR 5 the start page and the licence gate (#38), PR 6 statement pages with autosave (#39), PRs 7 and 8 combined: review, submit, history and result (#40), PR 9 the survey wording in the admin (#42), PR 10 docs and the last small fixes (#43), then two admin fixes: allauth's admin section renamed (#45) and its email addresses page made read-only (#46). 460 tests. **Status (2026-11-12).** The founder ran the live checks for Milestone 2 (tasklist parts A to D) and every "Done when" box below is ticked; PR 11 recorded it. The founder closed Milestone 2 on 2026-11-12. Milestone 3 starts when the founder says so. The Milestone 1 browser checks and the uptime checker are still in `06-backlog.md`. The PR plan below is the revised one agreed with the founder; the original ten-PR list is superseded.

**The product rules, as specified by the founder**

- The Accelerare Personality Diagnostic: 25 statements, each rated 1–4 (forced choice, no midpoint). The four labels are fixed for every statement: 1 "This does not describe me", 2 "This slightly describes me", 3 "This mostly describes me", 4 "This describes me very accurately" (full sentences in the template).
- Five pages of five statements, in position order. Within a page the person may change any of the five answers. Clicking **Next** locks the page; locked answers can never be changed, and there is no back button.
- Progress is saved on the server: every click is saved as it happens, and the response remembers how many pages are locked. Closing the browser, an outage or a new device resumes on the first unlocked page with the saved clicks selected.
- **Licences.** Registering is free, but the statements sit behind a paywall. A licence (the `Entitlement` row from the architecture doc) is one survey attempt plus the results at its tier. Any tier (1–3) unlocks the survey. Upgrading a licence raises its tier in place, so the same response shows more results. A retake needs another licence. Until payments exist (Phase 3), root admin grants licences by hand in the Django admin after invoicing. Enterprises buying licences in assorted tiers for their members is Milestone 4.
- **Tier 0.** An account with no active licence is at "tier 0", the free tier. That is a display state, not a licence row: the history and result pages show what a free account gets. The founder's suggestion for Milestone 5 is sample or limited insights from the purchasable tiers; the content is undecided.
- **What a person sees.** With or without a licence: their account, their survey history (each response with date, status and tier) and, from Milestone 5, the results and insights their tier allows. Never, at any tier: the statements outside an attempt in progress, or their own answers once submitted. Root admin keeps the read-only Django admin view of answers. Whether enterprise administrators see answers is undecided; see `06-backlog.md`.
- **Erasing an account** (built, PR 3b). An account with no completed (submitted) survey is hard-deleted outright, with its contacts, licences, unfinished attempt and person. An account with a completed survey is stripped, not deleted: email, phone, name and login are removed and the results are kept, with `Account.anonymised_at` marking it so enterprise reports can show current members apart from the historical total. The same email can then sign up again as a fresh account. The strip list lives in one place (`apps/accounts/erasure.py`, `_anonymise`). Demographics (age, gender, company) belong on `Person`, never on the account, so erasing leaves them alone. Whether the kept data is anonymous enough is a question for a privacy lawyer before launch.
- **Self-report.** The survey asks "Have you taken this survey before?" (Yes or No, required). If yes, "How did you take it?" is a required drop-down: Individual, Company or Other. An optional free-text box for information that would help match the old account arrives in Milestone 5 with the matching that uses it; it is cleared once matching has been attempted, unless it produced a link. No free text is collected in Milestone 2.
- **Funnel** (built, PR 3c). Sign-up, first verified email, licence granted, licence upgraded, survey started, page finished and survey submitted are recorded as events with no link to any account, so erasing someone never changes the counts. The admin shows a summary with conversion percentages.
- **Licences do not expire.** Staff get an "unused licences" filter (any, 7+ days, 30+ days) in the licence admin to decide who to nudge.
- **Revoking a licence** (built). An unfinished attempt on it is deleted: it could never be continued, and it would block the account from starting on another licence. A submitted survey is kept, but its result and history show the free tier, "Free (licence withdrawn)", with no results, as a refund would. The admin's message and history say when a draft was deleted.
- **Tier names** are placeholder words for now ("Tier 1", "Tier 2", "Tier 3", and "Free" for tier 0), kept in one template (`templates/responses/_tier.html`) until the founder names the tiers.
- **Dates** on the history and result pages are the day only ("10 October 2026"), in UTC, so they can be a day off for people far from UTC until accounts have a time zone.
- The intro text and the scale labels are public (they live in templates). The statements, the algorithm and the insights are private. The algorithm and insights are Milestone 5 and may end up in a second private repository; nothing in this milestone depends on that choice.

**What you build**

- `apps/survey/models.py`: `SurveyVersion` (number, published_at, question_count), `Question` (survey_version FK, position, text, min_value, max_value, `metadata` JSONField default dict for whatever per-question fields arrive later). A data migration creates version 1 with 25 rows whose text is the placeholder "Question *n*", 1–4. A management command `load_questions <path>` reads a JSON file of 25 entries (`position`, `text`, any extra keys go into `metadata`) and updates the rows by position; it refuses a file that does not have exactly 25 positions 1–25. A helper `survey.services.current_version()`.
- The private file. The real statements arrive as a JSON file the founder keeps outside the repository. **Built in PR 9 (#42), as confirmed by the founder on 2026-10-09:** a superuser-only admin page where the founder pastes or uploads the JSON, sees how many questions will change, and applies it through `survey.services.load_questions`; no SSH, no server mount, no `deploy.sh` step. On a laptop the file still lives in the gitignored `private/` directory and is loaded by hand with `manage.py load_questions`. GitHub never sees it: CI and the image smoke test run on the placeholder rows, and the loader's tests use `tests/fixtures/questions_sample.json`, a committed file with made-up wording. (The original plan mounted `/opt/survey/private/survey_v1.json` into the container and ran `load_questions` in `deploy.sh`; it is dropped.)
- *Built in PR 2, with `change_tier` and an unused-licences filter added.* `apps/entitlements/models.py`: `Entitlement` (person FK, tier 1–3, source purchase/manual, granted_by FK nullable, granted_at, revoked_at nullable). This is the individual half of the Milestone 4 table; Milestone 4 adds the nullable membership FK, the seat source and seat pools to the same model. `apps/entitlements/services.py`: `grant_individual(person, tier, source, granted_by)`, `revoke(entitlement)`, `unused_licence(account) -> Entitlement | None` (active, not yet linked to a response, oldest first), `has_survey_access(account)` (an open draft or an unused licence). Root admin: `Entitlement` in the Django admin with account search, grant through a form that calls the service, a revoke action, and the tier editable in place for upgrades. A decorator `entitlements.decorators.survey_access_required`, stacked on `accounts.decorators.verified_email_required`.
- *Model built in PR 3; the self-report column is changed in PR 4.* `apps/responses/models.py`: `Response` (account FK, survey_version FK, `entitlement` OneToOneField to `Entitlement`, status draft/submitted, answers JSONField default dict, `pages_completed` small integer default 0, `took_before` bool nullable, `took_before_via` (individual, company, other; set only when `took_before` is yes; replaces the text column `took_before_where`), started_at, submitted_at nullable, possible_repeat bool default False). A `Meta` constraint: `submitted_at` is null if and only if status is draft. The one-to-one makes "one licence, one attempt" a database rule. The nullable membership FK from the architecture doc is added in Milestone 3 with its own migration, when `Membership` exists.
- `apps/responses/services.py`: `start_response(account)` (returns the open draft if there is one; otherwise consumes the oldest unused licence and creates a draft on the current version; raises `NoLicence` if there is none), `save_answer(response, question_id, value)` (validates the id belongs to the version and the value is in range; refuses a locked page, a later page than the one being answered, or a submitted response), `complete_page(response, page, answers)` (saves the ticks the page showed, then refuses unless all five answers on that page exist, the page is the next unlocked one and, for page 1, the self-report is answered; an incomplete page keeps the ticks it was sent; bumps `pages_completed`), `submit(response)` (all pages locked and every question answered; sets status and timestamp in a transaction; enqueues jobs from Milestone 5 onward). A refused write raises `Refused` or a subclass (`NoLicence`, `Locked`, `Incomplete`, `Invalid`). Every service locks the row and returns the fresh instance; callers use the return value. A deleted draft raises `Response.DoesNotExist`.
- Views, all under `/survey/` (built): `responses:start` at `/survey/start/` (disclosure page, FR-15, and the self-report form, FR-16: Yes or No, then a required Individual/Company/Other drop-down; a GET writes nothing, the POST creates or resumes the draft and goes to the first unlocked page; without a licence it shows the same page with a "you need a licence" notice and no form; with a draft past page 1 it shows Continue). The pages of one attempt are `/survey/<id>/...` (the id stays because Milestone 3 allows a personal and an enterprise draft at once): `responses:resume` at `<id>/` (goes to the first unlocked page, or the review), `responses:page` at `<id>/page/<n>/` (renders the page being answered; any other number redirects to it), `responses:save_answer` at `<id>/save/` (HTMX POST, saves one answer, returns the statement as saved; 409 with the reason on a refusal), `responses:next_page` at `<id>/next/` (ordinary POST of the page's ticks, locks the page; already locked means a double click and carries on quietly), `responses:review` at `<id>/review/` ("25 of 25 answered", submit button; no answers shown), `responses:submit` at `<id>/submit/` (lands on the result with "Submitted."). `responses:history` at `/survey/history/` (own responses: date, status, tier; Continue when a draft is open, Start with the count of unused licences, "Free account" when no licence counts) is the hub: the profile's survey box and a "My surveys" header link point to it. `responses:result` at `<id>/result/` (one submitted response: date, tier, and a results placeholder until Milestone 5; never the answers).
- Templates: `responses/disclosure.html`, `page.html` (five statements) and `_statement.html` (HTMX partial), `review.html`, `history.html`, `result.html`, `_tier.html` (the tier's name, in one place). Script: `static/js/survey-page.js`.
- Root admin: *built in PR 3.* `Response` is read-only for everyone. Superusers see the answers and self-report; other staff see which questions are answered by position and never the values.

**Technical detail**

- `answers` is a JSON object keyed by question id as a string: `{"1": 3, "2": 4}`. Using the database id rather than position means a future reordering of questions does not corrupt old answers.
- Page *n* holds the statements with positions 5n-4 to 5n; page size is a constant in `survey`. Page *n* is locked when `pages_completed >= n`.
- Autosave: the page is one form posting to Next, so Next works without JavaScript and locks exactly what the page shows. Inside it, each statement is a `<fieldset>` with four radio buttons and `hx-post` to `responses:save_answer` on `change`. A second click while one is saving waits its turn (`hx-sync="this:queue last"`), and the reply replaces only the statement's status line (`hx-select`), never the buttons, so a slow reply cannot undo a newer click. The CSRF token is on `<body>` through `hx-headers` (Milestone 1). HTMX does not swap a 4xx reply by default, so `survey-page.js` lets the 409 through; it also keeps Next disabled until all five are chosen (the service check is what enforces it) and shows "Saving…", "Saved" or "Not saved". A redirect during an HTMX save (expired login, lost licence, page locked in another tab) becomes an `HX-Redirect` header so the whole window moves.
- Resume: `responses:resume` redirects to page `pages_completed + 1`, to review when all pages are locked, or to the start page when the self-report is missing. Only the page being answered is ever shown. Statement pages are never cached, so the back button asks the server again and cannot reopen a locked page.
- Immutability: `save_answer`, `complete_page` and `submit` check status and page locks. `Locked` means "already done", so views redirect on it (a double click, another tab); other refusals are a 409 for the autosave or a message on the page. The admin makes fields read-only. There is no model-level lock; the service layer is the gate, which is why all writes go through services.
- Concurrency: a person with two tabs open can race `save_answer`. Use `select_for_update()` on the response row inside the service so the JSON update is serialised. `complete_page`, `submit` and `start_response` (which must not consume one licence twice) use the same lock.
- Access: every response view is behind `verified_email_required`. The pages of one attempt use `_own_draft_required` (in `apps/responses/views.py`): a submitted response goes to its result first (so a double click on Submit never meets the licence gate), then `survey_access_required` (login, verified email, licence), then ownership: your own draft on a licence that is not revoked, or a 404. History and result need only a verified email, and their templates get a summary (date, status, tier), never the response, so no template can print the answers.
- The results tier of a response is read live from `response.entitlement.tier`, so an upgrade shows more without touching the response.
- The disclosure text names the viewer: "your answers will be visible to you and to Accelerare" for individuals; milestone 3 adds that <enterprise name>'s administrators see the response's status, date and tier (and later its results), never the answers (decided 2026-11-12).

**Tests**

- Migration creates 25 questions, positions 1–25, all 1–4, with placeholder text.
- `load_questions` applies the sample file (text and metadata) and refuses a file with 24 entries or a duplicate position.
- `grant_individual` then `has_survey_access` is true; after `revoke` it is false; `unused_licence` skips a licence already linked to a response and returns the oldest.
- `start_response` with no licence raises `NoLicence`; with one licence it creates a draft linked to it; called twice it returns the same draft; after submit it raises `NoLicence` again until a second licence is granted; two concurrent starts consume one licence (lock asserted).
- `save_answer` rejects value 0, 5, a non-integer, an unknown question id, a question on a locked page or on a later page, and any write to a submitted response.
- `complete_page` refuses with four of five answered and succeeds with five; it refuses a page that is not the next unlocked one.
- Resume lands on page 2 after locking page 1 with answers saved out of order, and shows the saved answers for page 2.
- `submit` fails with four pages locked and succeeds with five; after success, `save_answer` returns 409.
- A verified user without a licence sees the notice on `start` and is refused on every statement page; the same user still reaches history and result.
- History shows only the user's own responses; `result` for another user's response returns 404; `result` and `history` never contain a statement or an answer value.
- Page tests: disclosure, page, review, history and result render for a verified licensed user; all redirect for an unverified user.

**PR plan** (revised 2026-10-09; one branch and one pull request each, in this order)

*Merged:*

1. `m2-survey-models` (#31): survey app, models, placeholder migration, `load_questions`, `current_version()`, admin, sample fixture.
2. `m2-entitlements` (#32): `Entitlement` (individual half), `grant_individual`, `revoke`, `change_tier`, `unused_licence`, `has_survey_access`, admin grant form and revoke action.
3. `m2-response-model` (#33): `Response` with the licence one-to-one, one open draft per account, the submitted-at rule, licence access now counting responses, the two-level response admin, the "Support staff" group.
3b. `m2-erase-account` (#34): `Account.anonymised_at`, `erase_account` (hard delete or strip the identity), the Erase button and confirmation page, admin history scrubbed of the email, revoke recorded in the history.
3c. `m2-funnel-events` (#35): `FunnelEvent`, events for sign-up, first verified email, licence granted and upgraded, the admin funnel summary, the unused-licences filter, Support staff can view the funnel.
4. `m2-response-services` (#37): `took_before_via` replaces `took_before_where`; `start_response`, `save_self_report`, `save_answer`, `complete_page`, `submit` under `select_for_update`; the `Refused` exceptions; funnel events `survey_started`, `page_locked` (with the page) and `survey_submitted`, all with tier and source; revoking deletes an unfinished draft.
5. `m2-disclosure` (#38): `/survey/` URLs, `responses:start`, the disclosure text, the self-report form, the no-licence notice, `survey_access_required`, the profile link, page tests.
6. `m2-pages-autosave` (#39): the statement pages, autosave, Next and resume; answers only for the page being answered; Next saves the ticks shown; real-browser checks at phone width.
7 and 8. `m2-review-submit-history` (#40, combined at the founder's request so Submit lands on a real result page): review, submit, history and result; "Free (licence withdrawn)"; history is the hub.

9. `m2-survey-wording-in-admin` (#42; confirmed by the founder on 2026-10-09; replaces "deploy the private file"): a superuser-only "Load the survey wording…" button on the current survey version's admin page. Paste or upload the JSON, Check shows how many statements change (counts only, never the wording) and how many unfinished and submitted attempts are on the version, and Apply goes through `load_questions` (version row locked; refused if someone changed the wording since the preview; a submitted survey on the version needs an "I understand" tick). Plain-English errors (not JSON, wrong count, duplicate or missing position, empty text, over 200 KB or 1,000 characters a statement, values the database cannot store); the history entry records who did it and the counts. Support staff cannot see or reach it. Sentry no longer receives request bodies or local variables.
10. `m2-docs` (#43): the docs synced with PR 9; NOTES entries; Caddy refuses request bodies over 5 MB and `deploy.sh` reloads Caddy on every deploy; the licence grant form searches for the account instead of listing every one; a test for a refused password-reset mail; the founder's remaining live checks collected into one tasklist.

After PR 10: `m2-admin-section-labels` (#45), allauth's admin section is called "Login (allauth)"; `m2-allauth-emails-read-only` (#46), its email addresses page is read-only apart from "mark verified".

11. `m2-live-checks` (the founder, then a docs-only PR): the founder worked through parts A to D of the tasklist on the live site (reported 2026-11-12); the PR ticks the Milestone 2 "Done when" boxes, moves the finished parts to the decision log and fixes the docs that had fallen behind.

**Done when** *(the live checks were run by the founder and reported on 2026-11-12)*

- [x] On the live site, a verified account without a licence sees the notice and cannot reach a statement; after root admin grants a licence in the admin, the same account can take the survey on a phone, close the browser mid-way, reopen, resume on the right page, and submit.
- [x] The live site shows the real statements, not placeholders, and the public repository contains none of them.
- [x] After submitting, the response appears in history with its tier, no page shows the answers, and a second attempt needs a second licence.
- [x] Root admin sees the response in the admin, read-only; a Support staff account sees which questions are answered but not the values.
- [x] On the live site, a test account is erased from the admin both ways (one with no completed survey, one with a completed survey) and the same email can sign up again.
- [x] The funnel page in the admin shows the live sign-ups, verifications, licences and survey events.
- [x] All tests pass. *(457 passed, ruff, `check --fail-level WARNING` and `makemigrations --check` clean, 2026-10-10; 460 in CI after #46.)*

**Why this order / what to understand**

This is the first milestone that delivers the product's core, and it does so before enterprises exist. That's deliberate: the survey flow for an individual and for an enterprise member is identical except for one nullable foreign key. Building it once in the simple case and then adding the key is less work than designing both at once.

*Why questions live in the database.* The placeholder migration and the private file are just the way v1 gets in. From then on, the code never knows what the statements say; it reads them. Version 2 is a new `SurveyVersion` row plus questions, and old responses still point at version 1, so the detail page renders them correctly forever.

*Why a private file rather than a private repository.* The repository and the Docker image on ghcr.io are public, so anything committed is readable by anyone and anything built into the image is too. The statements are data that changes rarely, so a file copied to the server once, outside the image, keeps them out of both with no new accounts or tokens. Code (the algorithm) cannot be delivered that way comfortably; that decision is deferred to Milestone 5.

*Why the licence table comes forward from Milestone 4.* A paywall needs a record of who paid for what, and the architecture already names it: `Entitlement`. Building a throwaway "can take the survey" flag now and replacing it later would mean a migration to remove it and a second set of tests. Pulling the individual half of the real table forward costs the same effort once. The one-to-one from `Response` to `Entitlement` is what makes "one licence, one attempt" a rule the database enforces rather than a convention.

*Why JSON for answers.* The alternative is an `Answer` table with one row per question per response. For 25 numeric answers with no branching, that's 25 rows to write per response and a join to read, for no benefit. JSON keeps the whole response in one row, which also makes the CSV export and the algorithm input trivial. PostgreSQL's JSONB is indexed and queryable if you ever need it.

*Why services, not views.* The `submit` rule ("all pages locked, all 25 in range, status draft, set timestamp, enqueue jobs, all atomic") must be identical whether triggered from the web, a test, or a future admin action. If it lives in a view, it's only available to the view. Putting it in `services.py` makes the view five lines and the rule one place.

*What HTMX is doing.* Normally a form submit replaces the whole page. HTMX intercepts it, sends the request in the background, and swaps the server's HTML response into a target element. The server still renders HTML; there's no JSON API and no client-side state. When something looks wrong, open the browser's network tab: you'll see a normal POST and a normal HTML response.

*Why `select_for_update`.* Two requests can read `answers = {"1": 3}`, each add a key, and each write back, losing one answer. Locking the row for the duration of the update prevents it. It costs nothing at your traffic and prevents a bug that is nearly impossible to reproduce by hand.

---

## Milestone 3 — Organizations, memberships, invites and codes

*Re-planned on 2026-11-12 with the founder. This section replaces the original one; the differences are in the decision log. The site says "organization"; the code, the tables and these docs keep the word "enterprise" for the same thing.*

**Goal:** anyone can create an organization and become its admin; admins invite by email or issue join codes; people join through either; a licence tied to a membership lets a member take the survey for the organization; admins see who took it, when, its status and tier, never the answers; nothing from one organization is ever visible to another.

**Status (2026-11-13).** Code-complete and deployed. Merged: PR 0 the re-plan (#50), PR 1 the full name (#51), PR 2 the models (#52), PR 3 the services (#53), PR 4 invites (#54), PR 5 membership licences (#55), PR 6 the context of a response (#56), PR 7 the survey pages per context (#57), PR 8 the organization pages (#58), PR 9 the codes and invites pages (#59), PR 10 the join pages (#60), PR 11 the responses pages (#61), PR 12 the staff admin (#65), and PR 13, these docs. Three small PRs outside the plan, asked for by the founder on 2026-11-13: #62 removed screenshots committed by mistake, #63 made the test suite about six times faster, #64 gave the site a page at `/`. 1,020 tests. An end-to-end run in a real browser passed on 2026-11-13 ("Checks at the end", below). What remains is the founder's live checklist (below, and `06-backlog.md` T-16): the first six "Done when" boxes stay unticked until it has been run on the live site. Merging on green without review ended with this milestone.

**How this milestone is run** (founder, 2026-11-12). Each PR is built, tested, opened, merged once CI is green and checked on the live site without waiting for the founder's review. Anything that is the founder's decision (a product rule, a privacy question, anything not settled below) is raised with them and waits for their answer. Every PR ends with a short summary of what was done and which small calls were made. The milestone ends with automated checks and a hand-run checklist for the founder.

**The product rules, as decided by the founder on 2026-11-12**

- **Creating.** Any account with a verified email can create an organization, with no review, and becomes its first admin. Two organizations may share a name; each gets its own slug.
- **Admins.** An admin can make a member an admin and make an admin a member again. The last active admin can never be demoted or deactivated. Staff can do the same in the Django admin. An admin is also a member: they can take the survey for their own organization.
- **The people limit.** Until an organization has bought licences it can bring in at most 25 people in total, by email invite or by join code (`Enterprise.people_limit`, default 25). Every invite ever sent counts, including revoked and expired ones, plus every join by code, so revoking and resending does not get round it. The creator does not count. Staff raise the number by hand in the Django admin; how buying licences raises it was a Milestone 4 question, settled on 2026-11-13: the limit is this number plus the licences bought (see Milestone 4). Joining only makes someone a member; taking the survey still needs a licence.
- **Licences.** A licence (`Entitlement`) belongs to a person or to a membership, never both. A membership licence can only be used for that organization and a personal one only personally, so the licence decides who sees the result. Until Milestone 4 adds seats, staff grant both kinds by hand in the Django admin. A person may have a personal attempt and an organization attempt open at the same time.
- **What an admin sees.** Of a member: name, email, joined date, status and licence tier; never the phone number and never a survey taken personally. Of a response taken for the organization: member, "In progress" or "Submitted", the start and submit dates, tier and the possible-repeat flag; never the answers, the self-report or how far along a draft is. Results are added in Phase 2.
- **What a member sees.** The organization's name and their own surveys. Never other members.
- **Joining tells the truth first.** Before someone joins, a confirmation page says what the organization's admins will be able to see. The survey's disclosure page says it again for an organization attempt.
- **Deactivating.** An admin deactivates a member who has left. Their unfinished attempt for the organization is deleted; the licence stays with the membership, unusable until they are reactivated; submitted surveys stay visible to the organization; the person keeps their own history. A deactivated member cannot rejoin with a shared join code: an admin reactivates them (a button) or sends a fresh invite.
- **Invites.** Single use, expire after 14 days, and can be accepted only by an account that has verified the invited address. The link does not verify the address. If the email cannot be sent (the SES sandbox, an outage), the invite is kept and the admin can copy the link.
- **Join codes.** Ten characters shown as `XXXXX-XXXXX`; the admin picks the number of uses and an expiry (30 days by default); any email may redeem one. A code or invite may carry a tier: the field was stored but hidden until Milestone 4 gave it meaning (PR 4: whoever joins is given a licence of that tier from the stock).
- **Erasure.** Erasing a person keeps their membership link (founder's choice, for the privacy lawyer to confirm; `06-backlog.md`, D-7). An account with a completed survey is stripped as before: its membership is deactivated and shows as "Erased member", its name is removed, and its address is removed from any invite that was sent to it. An account with no completed survey is deleted along with its memberships and their unused licences. How an organization's own request to delete all its members' data works is still open (D-2).
- **Names.** Sign-up asks for a full name (`Account.full_name`); accounts made before this are asked for it on the profile page. Erasing an account removes it.

**What you build**

- `Account.full_name` (blank for accounts made earlier), required on the sign-up form, editable on the profile, shown and searchable in the staff admin, cleared by `erasure._anonymise`.
- `apps/enterprises/models.py` (listed before `apps.responses`, which must stay last): `Enterprise` (name, slug unique, created_by FK nullable, created_at, people_limit default 25), `Membership` (account FK, enterprise FK, role member/admin, status active/deactivated, joined_at, deactivated_at nullable, joined_via_invite FK nullable, joined_via_code FK nullable; unique on account+enterprise), `Invite` (enterprise FK, email normalised, token unique, tier nullable, expires_at, accepted_at nullable, revoked_at nullable, created_by FK nullable, created_at), `JoinCode` (enterprise FK, code unique, tier nullable, max_uses, uses, expires_at, revoked_at nullable, created_by FK nullable, created_at; a check that uses never exceeds max_uses). No `__str__` contains an email, so no admin history label can.
- `apps/enterprises/services.py`: `create_enterprise(account, name)`, `create_code(admin_membership, max_uses, expires_at, tier=None)`, `revoke_code`, `redeem_code(code, account)`, `invite_by_email(admin_membership, email, tier=None)`, `revoke_invite`, `accept_invite(token, account)`, `deactivate_membership`, `reactivate_membership`, `set_role`, `places_left(enterprise)`. A refused action raises an exception whose message is plain words for the page.
- `apps/enterprises/scoping.py`: `for_admin(request, slug) -> Membership` loads the active admin membership of the logged-in account for that slug, and `for_member(request, slug)` the active membership of any role. Both answer 404 for a slug that does not exist and for one the account does not belong to, so nobody can probe which organizations exist. Every organization view starts by calling one of them.
- `apps/entitlements`: `Entitlement.person` becomes nullable, `Entitlement.membership` (FK, nullable) is added, with a check that exactly one of the two is set. `grant_for_membership(membership, tier, source, granted_by)`; `unused_licence` and `has_survey_access` take the context (a membership, or none for personal). The admin grant form takes an account (personal) or a membership.
- `apps/responses`: `Response.membership` (FK, nullable; null means personal), always equal to its licence's membership (the service enforces it). "One open draft per account" becomes one per account and context, in a new migration. `start_response(account, membership=None)` consumes that context's oldest unused licence.
- Survey pages per context: `/survey/start/` (personal) and `/survey/start/<slug>/` (for an organization, through `for_member`); the disclosure text has an organization version; "My surveys" lists each response with its context and offers Start or Continue per context; the result page names the context.
- Organization pages under `/organizations/`: the list of the account's organizations with "Create an organization", `new/`, and per organization (`<slug>/`) the dashboard, `members/` (name, email, role, status, joined date, licence; deactivate, reactivate, make admin, make member), `codes/` (list with uses, create, revoke), `invites/` (list, send, revoke, copy link, "18 of 25 places left"), `responses/` (a list with filters and a choice of order) and `responses/<id>/` (one response; 404 for any other organization's id). A header link and a box on the profile lead there.
- Join pages: `/join/code/` and `/join/invite/<token>/`. Logged out, the person signs up or logs in first and is brought back (the pending join is kept in the session; if it is lost, entering the code or opening the link again works). The sign-up funnel event records the channel `invite` or `code`.
- Email: the invite email, sent synchronously until the Milestone 5 worker exists, through the same failure handling as the other mails.
- Django admin (the hub): `Enterprise` (search, the people limit editable, create one for a customer with a first admin), `Membership` (actions that call the services: deactivate, reactivate, make admin, make member), `Invite` and `JoinCode` (read-only, with a revoke action). Support staff can view all four and deactivate a membership. Every action shows a confirmation page first and writes a history line.

**Built as planned, with these differences** (each is also in its PR's description)

- *Founder decisions taken during the build (2026-11-12).* An account can create three organizations itself; staff can create more for it. Erasing an account that is the only active admin of an organization with other active members is refused until someone else is made admin; with nobody else active it goes ahead and the organization is left empty. Deactivating an admin also makes them an ordinary member, so someone who comes back is promoted again on purpose. The email an organization's admins see for a member is the address the invite went to if they joined by invite, otherwise the one they log in with.
- *The responses page is a list, not a wide table, and has no HTMX.* The site's layout is one narrow column for phones. A small form (status, results level, possible repeats, order) reloads the page with query parameters; an unknown value shows everything. These two pages are served by the responses app (`apps/responses/organization_views.py`), because `enterprises` may not import a response.
- *Joining is two steps.* `services.check_code` and `check_invite` only read; the confirmation page is shown; only its button joins (`redeem_code`, `accept_invite`, which check everything again under their locks). Logged out, the join pages reveal nothing, not even whether a code or link is real; the typed code and where to come back to are kept in the session.
- *Organization pages hand their templates plain values, never database objects,* so a template cannot reach a phone number or an answer by accident; a test enforces it.
- *The staff admin asks "are you sure?" before every action* and writes a history line. Support staff get one new permission, `enterprises.deactivate_membership`, rather than the general change permission. A join code is shown only to superusers, an invite's link secret to nobody.
- *Words on the site.* A code is "switched off" and an invite "withdrawn"; a code's life is asked in days (1 to 365, 30 by default). The join and "Before you begin" pages say "results level" where the tier names will go (D-4); lists say "Tier 2".
- *Not built, on purpose:* an organization admin cannot rename the organization; staff cannot put a person into an organization directly (an invite or a code is the only way in); `Response.possible_repeat` is shown but nothing sets it until matching exists (Milestone 5).

**Technical detail**

- Dependencies run one way: `accounts` ← `enterprises` ← `entitlements` ← `responses`. `accounts` (erasure) reaches memberships through the reverse name `account.memberships`; `enterprises` reaches licences and responses through `membership.entitlements` and `membership.responses`, never by importing those apps.
- Tokens and codes: `secrets.token_urlsafe(32)` for invite tokens; join codes use a 10-character alphabet without ambiguous characters (no `0/O`, `1/I/L`), stored uppercase without the hyphen, compared after uppercasing and dropping spaces and hyphens.
- `redeem_code` and `accept_invite` run in one transaction. They lock the `Enterprise` row (so the people limit cannot be exceeded by two joins at once) and then the code or invite row (so a code cannot pass `max_uses`). Checks: not revoked, not expired, uses below the cap, places left, and the account's existing membership: active means "you are already a member"; deactivated is refused for a code and reactivated by an invite.
- `invite_by_email` locks the `Enterprise` row, refuses when no places are left, refuses a second open invite to the same address and an address that already belongs to an active member, then sends the mail. The count is every invite row plus the sum of `JoinCode.uses`.
- Accepting an invite requires the logged-in account to hold the invited address as a verified contact point. Otherwise the page says "this invite was sent to x@y; log in with that address, or add and verify it on your profile".
- One open draft per context: two partial unique constraints, one on `account` where the status is draft and the membership is null, one on `account, membership` where the status is draft and the membership is set. The pages of one attempt also check that its membership is still active.
- Erasure stays correct in every PR that adds something an account can own: memberships (PR 2), invites holding an address (PR 4), membership licences (PR 5), organization drafts (PR 6). `created_by` on the three models is set to null when that account is deleted.
- Scoping: the slug is in the URL for navigation only. `for_admin()` verifies that *this account* has an *active admin* membership for *that slug*; the returned membership's `enterprise` is then the only enterprise id used in any query in that view. The response detail page looks the id up inside that enterprise, so another organization's id is a 404.
- Filtering and sorting of the responses list through query parameters (`?status=submitted&sort=-submitted`), sent by an ordinary form that reloads the page; every value is checked against an allow-list (`apps/responses/forms.py`, `ResponseFilterForm`).
- Carried over from Milestone 2: organization reports show two views, current members (active memberships) and the historical total (including deactivated and erased members).
- Brute-forcing join codes is limited in Milestone 7 (rate limit on the join page); the code space is about 10^15.

**Tests**

- Tenant isolation (the most important tests in the project), written before the pages they protect: organizations A and B, each with one admin and two members, each member with a submitted response for the organization and one taken personally. A's admin, on `members`, `codes`, `invites`, `responses` and `responses/<id>` for a B response, sees nothing of B: the detail page is a 404, not a 403. B's member cannot open A's pages at all. A member (not an admin) of A cannot open A's admin pages. No organization page ever shows a personal response, an answer value or a phone number.
- Codes: `max_uses = 2` and three simultaneous redemptions give exactly two memberships (the lock is asserted); revoked and expired codes fail; a deactivated member is refused; an active member is told they already belong.
- Invites: accepted once by the matching verified address; a second accept fails; expired, revoked and wrong-address cases fail with the right message; an invite reactivates a deactivated member; a refused mail keeps the invite.
- The people limit: the 26th person is refused by invite and by code; revoked and expired invites still count; two joins racing for the last place give one member; raising `people_limit` lets the next one in.
- Roles: the creator is an admin; promote and demote work; the last active admin cannot be demoted or deactivated.
- Licences and responses: a membership licence starts an attempt only for that organization and a personal one only personally; a personal and an organization draft can be open together, two for one context cannot; deactivating deletes the organization draft and blocks its pages; reactivating makes the licence usable again.
- Erasure: an account with a completed survey keeps its (deactivated) membership, shows as "Erased member", loses its name, and its address is gone from its invites; an account without one is deleted with its memberships; the organization's historical total still counts the former member.
- Pages: every organization, join and survey-context page renders for the right role at phone width and redirects or 404s for the wrong one.

**PR plan** (one branch and one pull request each, in this order)

0. `m3-replan` (#50): this section, and the requirements, architecture and backlog brought in line with the decisions. Docs only.
1. `m3-full-name` (#51): `Account.full_name`, sign-up, profile, staff admin, erasure.
2. `m3-enterprise-models` (#52): the `enterprises` app, its four models and database rules, a minimal read-only admin, erasure handling for memberships.
3. `m3-enterprise-services` (#53): `create_enterprise`, join codes, deactivate, reactivate, `set_role`, the people limit, `scoping.py`; the concurrency tests.
4. `m3-invite-services` (#54): `invite_by_email`, `revoke_invite`, `accept_invite`, the invite email, erasure handling for invites.
5. `m3-membership-licences` (#55): `Entitlement.membership`, the exactly-one rule, `grant_for_membership`, context-aware `unused_licence` and `has_survey_access`, the admin grant form, erasure handling.
6. `m3-response-context` (#56): `Response.membership`, one open draft per context, `start_response(account, membership)`, deactivation deletes the organization draft.
7. `m3-survey-context-pages` (#57): start, disclosure, "My surveys" and result per context.
8. `m3-organization-pages` (#58): create, list, dashboard, members; the header and profile links; isolation tests first.
9. `m3-codes-invites-pages` (#59): the codes and invites pages with the places-left count; isolation tests first.
10. `m3-join-flows` (#60): join by code and by invite link, sign up then join, the confirmation page, the funnel channel.
11. `m3-responses-table` (#61): the admin's responses table and response page; isolation tests first.
12. `m3-enterprise-admin` (#65): the Django admin for the four models, the Support staff permissions.
13. `m3-docs-live-checks`: docs synced with what was built, NOTES, an end-to-end automated run, and the founder's live checklist.

Outside the plan, at the founder's request on 2026-11-13: #62 (screenshots committed by mistake in PR 10 removed), #63 (the test suite made about six times faster), #64 (a page at `/`, and backlog updates).

**Done when**

*The first six boxes are the founder's live checks (the checklist is below). Tick each only after it has been seen working on the live site.*

- [ ] On the live site: create an organization, make a join code, open an incognito window, sign up and join with the code, have staff grant that membership a licence, take the survey for the organization, and see the response in the admin's table and response page, with no answers anywhere.
- [ ] The same with an email invite (to an address SES can deliver to while it is sandboxed).
- [ ] Deactivate that member: they still see their own response, the admin still sees it, the shared code no longer lets them back in, and Reactivate does.
- [ ] Make a second admin; the last admin cannot be demoted or deactivated.
- [ ] With the people limit lowered to a small number in the Django admin, the next invite and the next code join are refused.
- [ ] Erase a member with a completed survey and one without: the first shows as "Erased member" and still counts in the historical total, the second is gone.
- [x] All tests pass, including every tenant isolation test. *(1,020 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,020 tests, including every tenant isolation test (`tests/test_tenant_isolation.py`), on the laptop and in CI. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. One end-to-end run in a real browser at phone width, against a local server, in eleven steps: an admin creates an organization and a join code; a stranger enters the code, signs up, verifies their email from the link in the mail, logs in, is brought back and joins (the funnel records the channel `code`); before a licence they are told they need one; staff grant the membership a licence in the Django admin; the member takes all 25 statements for the organization and submits; the admin sees the response with name, email, status, dates and tier, and no statement, answer or phone number on the table, the response page or the members page; the admin of a second organization sees none of it on any of their pages and gets a 404 for every address of the first; and the member, who is not an admin, gets a 404 on the admin pages.

*Not covered by that run* (covered by the automated tests, and by the live checklist below): the invite-by-email journey, deactivating and reactivating, the people limit, a second admin, and erasure. *Not covered by anything automated:* real email delivery through SES, and the live site itself beyond `/health` answering 200 after each deploy. The checklist below is what proves those.

**Live checklist (for the founder)**

Run this on the live site. Each part matches one "Done when" box; tick the box when the part has been seen working. You need: your superuser login (window 1, also used for the Django admin at `/admin/`), and a private or incognito window (window 2) for the second person. Use three email addresses of your own for the second, third and fourth person. Your own account needs a verified email to create an organization; if the site asks for it, verify it the same way as below. While SES is in its sandbox, mail only reaches addresses verified in SES; for any other address, mark it verified by hand: Django admin, "Login (allauth)", "Email addresses", tick the address, action "Mark selected email addresses as verified", Run. Nothing here needs SSH, the AWS console or GitHub.

*Part A: join by code and take the survey (box 1).*
1. Window 1: "Organizations" in the header, "Create an organization", type a name, create. You land on its page, "You are an admin of this organization."
2. "Join codes", "Create code". A code like `ABCDE-FGH23` appears.
3. Window 2: go to `/join/code/`, type the code, Continue. The page asks you to log in or sign up and does not name the organization. Press "Sign up" and fill in the form with the second person's details.
4. Verify that address (the link in the email, or the admin action above), then log in in window 2. You are brought back to a page headed "Join (your organization)?" that lists what its admins will see. Press the Join button. You land on the organization's page as a member. (If you are not brought back, enter the code again at `/join/code/`.)
5. Window 2: "My surveys" says there is no unused licence for the organization.
6. Window 1: Django admin, "Entitlements", "Add entitlement". Leave "Account" empty; in "Membership" search for the second person's email and pick "Membership N in (your organization)"; tier 2; source Manual; Save.
7. Window 2: "My surveys" now offers the survey for the organization. Start it; the "Before you begin" page says what the organization's admins will see. Answer all five pages and submit. The result page says "For (your organization)".
8. Window 1: the organization's page, "See responses". One row: the person's name and email, "Submitted", the dates, "Tier 2". Open it. No statement and no answer appears on either page. "Manage members" shows the person with no phone number.

*Part B: the same by email invite (box 2).*
1. Window 1: the organization's page, "Invites", type the third person's address, "Send invite". If the page warns that the email could not be sent (the SES sandbox), press "Copy link" beside the invite instead.
2. Window 2 (log out first): open the link from the email, or paste the copied one. Sign up or log in with that same address and verify it. You are brought back to the "Join ...?" page; join.
3. Repeat steps 6 to 8 of Part A for this person.

*Part C: deactivate and reactivate (box 3).*
1. Window 1: "Manage members", "Deactivate" beside the second person, confirm.
2. Window 2, logged in as the second person: "My surveys" still lists their submitted survey and its result still opens. The organization's page is now "Not found" for them.
3. Window 1: "See responses" still shows their response, marked as no longer a member.
4. Window 2: `/join/code/` with the same code is refused: the membership was deactivated, ask an admin.
5. Window 1: "Manage members", "Reactivate". Window 2: the organization's page opens again.

*Part D: a second admin (box 4).*
1. Window 1: "Manage members". Your own row, the only admin, has no buttons.
2. "Make admin" beside the second person. Both rows now have buttons. "Make member" beside the second person puts it back, and your row again has none.
3. In the Django admin, "Organizations" section, "Memberships": tick your own membership, action "Deactivate the selected memberships", Run, confirm. It is refused: "An organization needs at least one admin."

*Part E: the people limit (box 5).*
1. Django admin, "Organizations", open yours. "Places" says how many are left: 23 of 25 if you have sent one invite and one person has joined by code.
2. Set "People limit" to the number already used (2 in that case) and save. "Places" now says 0 left.
3. Window 1: "Invites", send one to any other address: refused, no places left.
4. Window 2: sign up the fourth person, verify the address, and enter the join code at `/join/code/`: refused, the organization cannot take more people at the moment.
5. Set the limit back to 25.

*Part F: erasure (box 6).*
1. The second person has a submitted survey. Django admin, "Accounts", open that account, "Erase this account…", type the email and a reason, erase. The summary says the person is removed and the results kept.
2. Window 1: "Manage members" shows "Erased member" with no email, deactivated; "See responses" still shows the response under "Erased member"; the organization's page still counts them under "Everyone who has ever been a member".
3. Window 2, as the fourth person: enter the join code again and join, and do not take the survey. Then erase that account the same way. The summary says the account will be permanently deleted. Afterwards they are gone from "Manage members", and "Everyone who has ever been a member" is one lower.

When every part passes, tell Claude: the six boxes are then ticked in a docs-only PR and the milestone is closed.

**Why this order / what to understand**

This is where the project becomes multi-tenant, and multi-tenancy is where products leak data. The single most valuable thing in this milestone is `scoping.for_admin()` and the tests that prove it works. Read that function slowly.

*The threat model, plainly.* An attacker signs up, creates their own organization, and now has an admin page. They look at the URL, `/organizations/their-slug/responses/42/`, and change `their-slug` to `acme`, or change `42` to `41`. If any view takes the organization from the URL and trusts it, or loads response 41 without checking that it belongs to the admin's organization, Acme's data is on the attacker's screen. The scoping helper makes this structurally impossible: the only enterprise id in scope comes from the attacker's own membership, so filtering by it returns nothing of Acme's. The 404-not-403 rule stops the attacker learning which ids and which organizations exist.

*Why the licence carries the context.* A response already points at exactly one licence. If the licence says "this is Acme's", the response is Acme's, and nothing can disagree. Letting the person pick a context separately from the licence would mean two facts that could contradict each other, and Milestone 4's seats would have had to undo it.

*Why invites and codes rather than domains.* Covered in the architecture doc, but worth repeating here because you'll be tempted to add a "join if your email ends in @acme.com" shortcut. Don't. It reintroduces the fake-organization problem and buys little, since the admin can send invites to the whole staff list in one go.

*Why locking matters for codes and the people limit.* Two people redeem the last use of a code at the same instant. Both read `uses = 9`, both write `uses = 10`, and you have eleven members on a ten-use code. The row lock makes the second redemption wait for the first and then see `uses = 10`. The people limit and, in the next milestone, seat pools have the same shape and the same fix.

*Why a limit before paying.* An organization costs nothing to create, and an invite sends an email in Accelerare's name. Without a limit, anyone could use the invite form to send mail to strangers, and Amazon pauses senders whose mail is reported. Twenty-five places is enough to try the product and too few to abuse.

*The admin table is a real product surface.* Organization customers will judge the product by this page. Keep it simple, but make filtering, sorting and the empty state work properly. "No responses yet. Invite members to get started" with a link beats a blank table.

---

## Milestone 4 — Licences for organizations (seat pools)

*Re-planned on 2026-11-13 with the founder, who took each decision below one at a time. This section replaces the original one. The site says "licences" and "stock"; the code, the tables and these docs keep "seat" and "seat pool" for the same things.*

**Goal:** an organization holds a stock of licences it has bought, per tier; its admins give them to members, change their tier and take them back; an invite or a join code can carry a tier so that joining brings a licence with it; and the number of people an organization may bring in grows with what it has bought.

**Status (2026-11-13).** Code-complete and live. PRs 0 to 4 are merged and deployed (#67 to #71), and PR 5 is the docs PR that wrote this paragraph; the suite stands at 1,259 tests. What remains is the founder's checklist on the live site (parts A to D below; `06-backlog.md`, T-18): four of the five "Done when" boxes can only be ticked there, and nothing in this milestone has yet been tried by a person on the live site. The choices made while building are listed under "Smaller rules"; the founder answered each of them on 2026-11-13 (three kept, two overruled, and two settled by those answers), and the changes that follow from the two overruled ones are built next, before payments. Outside the plan, at the founder's request on 2026-11-13: #72 (the tests' setup made cheaper, docs-only merges no longer deploy, and CI lists its slowest tests).

**How this milestone is run** (founder, 2026-11-13). As Milestone 3 was: each PR is built, tested, opened, merged once CI is green and checked on the live site without waiting for the founder's review; every decision that is the founder's is raised and waits for an answer; every PR ends with a short summary. The arrangement covers Milestone 4 only and is asked again for payments. (Asked on 2026-11-13: it applies again; see the decision log.)

**Where it starts from.** Milestone 3 already built the model half of the original plan. A licence (`Entitlement`) belongs to a person or to a membership, never both; a membership licence lets that member take the survey for that organization; staff grant both kinds by hand in the Django admin (`grant_individual`, `grant_for_membership`, source `manual`); a licence is one attempt and is upgraded in place (`change_tier`); revoking one deletes an unfinished attempt on it (`revoke`). `Invite.tier` and `JoinCode.tier` exist and are hidden. Each organization can bring in 25 people (`Enterprise.people_limit`).

**The product rules, as decided by the founder on 2026-11-13**

- **The stock.** For each organization and tier, a number: how many licences it has bought. Until payments exist (the milestone after this one), staff type it into the Django admin after a sale made off the site. Superusers and Support staff may both set it (the founder's choice "for now", because payments follow straight away and will set it without anyone typing).
- **What counts against it.** A licence counts against the stock of the tier it has now, from the moment an admin gives it to a member, until it is taken back. One whose survey has been submitted counts for good: it is spent. Only licences given from the stock count. A licence staff grant by hand is a gift on top and is outside the stock.
- **Giving.** An organization's admin gives a member a licence of a tier while the stock of that tier has one left. An admin can give one to themselves: an admin is a member.
- **Taking back.** The admin can take a licence back until its survey is submitted. If the member has started, their unfinished attempt is deleted, after a warning. Once submitted, it cannot be taken back.
- **Changing the tier.** Before the survey is submitted the admin can move a licence up or down. Afterwards only up. Either way the new tier must have one left, and the old tier gets one back.
- **A member who has left.** Deactivating a member leaves their unused licence with the membership, as decided in Milestone 3, and it works again if they are reactivated. The admin can also take it back to the stock with the same button.
- **A tier on an invite or a join code.** The admin may choose a tier when sending an invite or making a code. Each person who joins with it is given a licence of that tier from the stock. If none is left, they still join, without a licence, and the admin's page says how many people that happened to. *(Changed on 2026-11-13: the licence is now set aside when the invite or code is made, so none can be missing at the join; see "Milestone 4, second part".)*
- **The people limit** (was `06-backlog.md` D-16). The number of people an organization may bring in is its base number (25, which staff can still change by hand) plus every licence it has bought, across all tiers.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

- A member holds at most one unused licence for an organization at a time; giving a second is refused with "they already have a licence they have not used". After they submit, they can be given another (a retake needs another licence, as everywhere).
- An organization's admin can take back or change only licences that came from the stock. One that staff granted by hand is staff's to change.
- Staff may lower a stock below what has been given (a customer downsizes, or a typing mistake is corrected). Nothing is taken from anyone; the page says "12 of 10 given" and no more can be given at that tier until it is back under.
- Taking a licence back keeps a record: it is revoked, not deleted, like every licence.
- Members are not emailed when they are given a licence; "My surveys" shows it. Email arrives with the Milestone 5 worker.

*Added while building (PRs 2 to 4) and raised the same way. The founder answered each on 2026-11-13; the answer is in bold. Where a choice was overruled, the site still behaves as written here until the licence changes are built.*

- One licence in hand at a time, whoever it came from: a member part-way through the survey is refused another until they submit, and an unused licence staff granted by hand also blocks giving one from the stock. **Kept.**
- The Licences page lists every active member, and a member who has left only while they still hold a licence. A licence that was taken back is not shown. A licence staff granted by hand is shown, marked "Granted by Accelerare, not from your stock", with no buttons. The drop-downs offer only tiers that have a licence left. **Kept.**
- The page a person reads before joining shows nothing of the organization but its name, so it does not say whether a licence comes with the invite or the code. Its last sentence was reworded, because "It does not by itself give you a licence" stopped being true (`06-backlog.md`, D-17). The message after joining says when they have a licence. **Overruled: the page must say so when the invite or the code comes with a licence.** The wording was left to the builder ("just do what makes sense"): with a licence, "Joining makes you a member. This invite comes with a licence to take the survey for (organization)." ("This code comes with…" for a code); without one, "Joining makes you a member. To take the survey for (organization) you also need a licence from it, which it may give you later." The tier is not named.
- A member who comes back with an invite that carries a tier keeps an unused licence they already hold and gets no second one. **Kept: it follows from one licence in hand at a time.**
- A tier can be chosen for an invite or a code while the stock has none: the stock is checked at the moment of joining, not when the invite or code is made. **Overruled, with a new design:** a licence is set aside out of the stock when the invite or the code is made, and making one is refused when none is left. An unused invite can be emailed again or moved to another address; the old link then stops working and the licence follows the new address. An invite may be emailed five times in all. Withdrawing an invite, or letting it expire, returns its licence to the stock. For a join code (left to the builder: "just do whatever makes sense to you") one licence is set aside for each person the code allows, and those not used return when the code is switched off or expires.
- The warning counts a member until they have had any licence for the organization, from an admin or from staff, and not again if that licence is later taken back. An admin who decides not to give one keeps seeing the warning. **Falls away:** once licences are set aside, nobody joins without the licence their invite or code promised, so the warning is removed with that work.
- The licence given on joining records as its giver whoever made the invite or the code. **Not raised as a question; stays as built.**

**What was built** (as built; where it differs from the plan of PR 0 it says so)

- `apps/enterprises/models.py`: `SeatPool` (enterprise FK, tier 1 to 3, seats; unique on enterprise and tier). It lives in `enterprises`, not `entitlements`, because the people limit needs it and `enterprises` may not import upwards. In `apps/enterprises/services.py`: `set_seat_pool(enterprise, tier, seats)`, `seats_bought`, `seats_given`, `seat_summary` (per tier: bought, given, left; planned for `entitlements`, built here beside the stock it reads), `people_limit` and `places_left` (the base limit plus the seats bought, less invites sent and joins by code), `joined_without_licence` (the warning), `lock_for_admin` (the organization's lock, for the licences app), and the signal `member_joined`.
- `apps/entitlements`: the source `seat` on `Entitlement`. In `services.py`: `assign_seat(admin_membership, member_membership, tier)`, `take_back_seat(admin_membership, entitlement)`, `change_seat_tier(admin_membership, entitlement, tier)` and `give_seat_on_joining(membership, tier)`. They raise `Refused` with a message for the page, or `NotFound` for a member or licence of another organization. `signals.py` listens for `member_joined`. The funnel records `licence_granted` with source `seat`.
- Django admin: the "Licence stock…" page of an organization, for superusers and Support staff (permission `enterprises.change_seatpool`), with a history line for every change; the organization's page shows bought, given and left per tier, and the people limit with its sum. The tier of an invite and of a join code shows on their own admin pages.
- The organization admin's "Licences" page, `/organizations/<slug>/licences/` (`apps/entitlements/organization_views.py`, listed in `config/urls.py` like the responses pages): the stock per tier ("7 of 10 Tier 2 licences left"), and each member with their licences and the state of each (not used yet, survey in progress, survey submitted), with Give licence, Change tier and Take back (which has a confirmation page, with a warning when an unfinished survey will be deleted). The dashboard has a "Licences" box, and the members page keeps its licence column and links to the page.
- The tier drop-down on the invite form and the join code form (optional; "No licence" by default). Joining with a tier gives the licence. A warning on the Licences page and the dashboard counts members whose invite or code carried a tier and who got none, and the Licences page marks each.

**Technical detail**

- Dependencies still run one way: `accounts` ← `enterprises` ← `entitlements` ← `responses`. `enterprises` tells `entitlements` that someone joined through a signal it sends (`member_joined`, with the membership and the tier), the same pattern as `account_erasing` in Milestone 3. The receiver never raises: a join must not fail because of the stock.
- Counting is computed, never stored: licences with source `seat`, not revoked, on memberships of that organization, grouped by tier. A stored counter could drift from the licences.
- Every function that counts first locks the organization's row, then the membership, then the licences, in that order, so two admins giving the last licence at the same moment take turns and exactly one succeeds. This is the order Milestone 3's deactivation and survey start already use.
- Giving a licence on joining has nobody acting: the admin chose the tier when they made the invite or the code and may not be an admin any more. So `give_seat_on_joining` does not check an acting admin; it takes the same locks in the same order and records whoever made the invite or code as the giver. The join's listeners run inside a savepoint, so even a database error in one of them is rolled back on its own and the join is kept (NOTES 2026-11-13).
- `take_back_seat` is `revoke` with the rules above in front of it (from the stock, not submitted, the acting admin's own organization). `change_seat_tier` is `change_tier` with the stock check and the up-only rule after submission.
- The acting admin is checked again inside the function, as in Milestone 3 (`by` is an active admin of the same organization), and the member's membership must belong to that organization; a licence id from another organization is "not found".
- Erasure needs no new rule: an erased account's unused membership licences are already deleted or revoked (Milestone 3, PR 5), which puts them back in the stock; a submitted one stays spent.
- The warning for joins without a licence is computed: active members whose `joined_via_invite` or `joined_via_code` has a tier and who have never held a licence for the organization.

**Tests**

- The stock: a pool of 2 refuses the third licence; two admins giving the last one at the same moment (threads) produce exactly one; the lock is asserted.
- Taking back: allowed when unused and when in progress (the draft goes, the licence is free again), refused when submitted; a licence staff granted by hand is refused; a deactivated member's unused licence can be taken back.
- Tier changes: up and down before submission move one between two stocks or change nothing if the new tier is full; down after submission is refused; up after submission works.
- Counting: a manual grant does not count; a revoked licence does not count; a submitted one counts for good; lowering the stock below what is given blocks new ones and removes none.
- The people limit: 25 plus the seats bought; the 26th person gets in once a licence has been bought; staff changing the base still works.
- Tier on join: an invite and a code with a tier give a licence on joining; with none left the person joins without one and the warning counts them; a join never fails because of the stock.
- Tenant isolation, written before the page: organization A's admin cannot see B's stock or members on the Licences page, cannot give a licence to B's member, and cannot take back or change B's licence (404, not 403); a member who is not an admin cannot open the page.
- Staff: superusers and Support staff can set a stock; a staff account outside the group cannot; the history line names nobody.
- Erasure: erasing a member with an unused licence from the stock frees it; with a submitted one it stays counted.

**PR plan** (one branch and one pull request each, in this order; all merged)

0. `m4-replan` (#67): this section; the US-first decision and the payments milestone recorded; D-16 and T-12 closed in the backlog. Docs only.
1. `m4-seat-pools` (#68): `SeatPool`, the staff admin for it, the people limit rule, the source `seat`.
2. `m4-seat-services` (#69): give, change tier, take back, the summary; the concurrency tests; the funnel event; erasure tests.
3. `m4-licences-page` (#70): the organization admin's Licences page and the dashboard box; isolation tests first.
4. `m4-tier-on-join` (#71): the tier on the invite and code forms; a licence on joining; the warning.
5. `m4-docs-live-checks`: docs synced with what was built, an end-to-end automated run, and the founder's live checklist. Docs only.

**Done when**

*The first four boxes are the founder's live checks (the checklist is below). Tick each only after it has been seen working on the live site.*

- [ ] On the live site: staff set an organization's stock in the Django admin; its admin gives a member a licence on the Licences page, the member takes the survey for the organization, and the counts are right at each step.
- [ ] The admin changes an unused licence's tier and takes one back; a submitted one cannot be taken back.
- [ ] A join code carrying Tier 2 can be made only while the stock covers everyone it allows, and gives the person who joins a Tier 2 licence. *(Reworded on 2026-11-13 with the second part of this milestone: nobody joins without the promised licence any more, so there is no warning to see.)*
- [ ] With 25 people brought in, the next is refused; after staff add a licence to the stock, the next gets in.
- [x] All tests pass, including every tenant isolation test. *(1,259 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,259 tests, including every tenant isolation test, on the laptop and in CI. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Each feature PR was also checked by breaking the code on purpose and confirming a test fails: nine breaks in PR 1, seventeen in PR 2, twenty-one in PR 3 and twenty-four in PR 4. Two were not caught at first. One (PR 3: the page looking a member up in any organization) is refused by the service underneath, and breaking both together fails two isolation tests. The other (PR 4: a lock that the join already holds) got a test of its own.

One end-to-end run in a real browser at phone width, against a local server, in sixteen steps: staff set the stock on the "Licence stock" page of the Django admin (two Tier 2, one Tier 3) and the people limit becomes 28; the admin gives a member a Tier 2 licence on the Licences page (1 of 2 left); the member starts the survey for the organization and the admin sees "Survey in progress" with the count unchanged and nothing about how far they have got; the member answers all 25 statements and submits; the admin sees "Survey submitted", no "Take back", and the licence still counted; the admin gives a second member a Tier 2 licence, changes it to Tier 3 (both counts move) and takes it back after the confirmation page; the submitted licence cannot be taken back even by typing the address; the admin makes a join code that gives a Tier 2 licence; the next person to join with it has the last Tier 2 licence straight away and is told so; the person after that joins without one; the admin sees the warning on the dashboard and on the Licences page with that person marked; with the base people limit set to 0 in the Django admin the three licences bought let three people in and the fourth is refused; staff add one licence to the stock and the same person gets in; the admin gives the new licence to the person who joined without one and the warning drops by one. No statement, answer or phone number appeared on the Licences page at any step, and nothing on it was wider than the phone. The run is a script outside the repository, like Milestone 3's.

*Not covered by that run* (covered by the automated tests, and partly by the live checklist below): a tier on an email invite, a member who comes back with an invite, taking back a licence whose survey is in progress (covered in PR 3's own browser check), a deactivated member's licence, two people joining at the same moment, a stock lowered below what is given, and erasure. *Not covered by anything automated:* the live site itself beyond `/health` answering 200 after each deploy. The checklist below is what proves that.

**Live checklist (for the founder)**

Run this on the live site. Each part matches one "Done when" box; tick the box when the part has been seen working. You need: your superuser login (window 1, also used for the Django admin at `/admin/`), a private or incognito window (window 2), and three accounts with verified email addresses for the second, third and fourth person. How to verify an address while SES is in its sandbox is in the Milestone 3 checklist above; accounts left over from that checklist will do. Start with a **new organization**, so that the numbers on your screen match the ones written here. Nothing here needs SSH, the AWS console or GitHub.

*Part A: staff set the stock, the admin gives a licence, the member takes the survey (box 1).*
1. Window 1: "Organizations", "Create an organization", give it a name. Then "Join codes": leave "Licence for each person who joins" at "No licence" and press "Create code".
2. Window 2, as the second person: go to `/join/code/`, type the code, Continue, Join. The message says "You have joined (your organization)." and nothing about a licence.
3. Window 1: Django admin, "Organizations", open the new one, then "Licence stock…" at the top right, beside History. Type 2 for "Tier 2 licences bought" and 1 for "Tier 3 licences bought", and press "Save the stock". Back on the organization's page, "Licences bought" reads "Tier 2: 2 bought, 0 given, 2 left; Tier 3: 1 bought, 0 given, 1 left" and "Places" begins "27 of 28 left".
4. Window 1: the organization's own page (not the Django admin). The "Licences" box says "2 of 2 Tier 2 licences left" and "1 of 1 Tier 3 licence left". Press "Manage licences". Beside the second person choose Tier 2 and press "Give licence". The page says they now have a Tier 2 licence, the stock says "1 of 2 Tier 2 licences left", and their licence reads "Not used yet".
5. Window 2: the organization's page, "Go to the survey", start it, answer the first page and press Next. Window 1: reload the Licences page. The licence reads "Survey in progress" and the stock still says "1 of 2".
6. Window 2: answer the other four pages and submit. Window 1: reload. The licence reads "Survey submitted", there is no "Take back" under it, and the stock still says "1 of 2 Tier 2 licences left": a used licence stays counted. "See responses" on the organization's page lists the survey at Tier 2.

*Part B: change a tier and take a licence back (box 2).*
1. Window 1: the Licences page. Beside your own name choose Tier 2 and press "Give licence". The page says "You now have a Tier 2 licence." and the stock says "0 of 2 Tier 2 licences left".
2. In the box of your licence choose Tier 3 and press "Change tier". The page says "The licence is now Tier 3."; the stock says "1 of 2 Tier 2 licences left" and "0 of 1 Tier 3 licence left".
3. Press "Take back" under your licence. A page asks "Take back this licence?" and says nothing of yours will be deleted. Press "Take back the licence". The stock says "1 of 1 Tier 3 licence left" and your row says "No licence".
4. The second person's licence, whose survey is submitted, still has no "Take back". Its tier can only go up: its drop-down offers Tier 3 and nothing lower.

*Part C: a join code that carries a tier (box 3).* *(Rewritten on 2026-11-13 for the second part of this milestone.)*
1. Window 1: "Join codes". The drop-down "Licence for each person who joins" now reads "Tier 2 licence (1 left)" and "Tier 3 licence (1 left)". Leave "How many people may use it" at 10, choose "Tier 2 licence (1 left)" and press "Create code". It is refused: the code "would give a Tier 2 licence to each of 10 people, but your stock has only 1 left".
2. Change "How many people may use it" to 1 and press "Create code" again. The new code's line ends "Gives a Tier 2 licence". On the Licences page the stock reads "0 of 2 Tier 2 licences left · 1 set aside for invites and join codes".
3. Window 2, logged in as the third person: `/join/code/`, that code, Continue. The last sentence above the button reads "Joining makes you a member. This code comes with a licence to take the survey for (your organization)." Press Join. The message says "You have joined (your organization). You have a licence to take the survey for it." Window 1: the Licences page shows the third person with a Tier 2 licence, "Not used yet", and the stock says "0 of 2 Tier 2 licences left" with nothing set aside.
4. Window 1: "Join codes", make another code with "No licence". Window 2, logged in as the fourth person: join with that code. The sentence above the button says a licence may be given later, and the message afterwards says only "You have joined (your organization)."

*Part D: the people limit grows with what was bought (box 4).*
1. Django admin, the organization. "Places" begins "25 of 28 left (0 invite(s) sent, 3 join(s) by code": 25 to start with, plus the 3 licences bought, less the 3 people who joined.
2. Set "People limit" to 0 and save. "Places" now begins "0 of 3 left": only the licences bought are letting people in.
3. Window 1: "Invites", type any address, "Send invite". It is refused: "(your organization) has no places left."
4. Django admin, "Licence stock…": type 1 for "Tier 1 licences bought" and save. "Places" begins "1 of 4 left".
5. Window 1: send the same invite again. This time it goes (while SES is in its sandbox the page may say the invite is saved but the email could not be sent; that is still a pass). On the Licences page, give the fourth person a licence (Tier 1 and Tier 3 each have one left).
6. Django admin: set "People limit" back to 25. Window 1: "Invites", "Withdraw invite" beside the test invite.

When every part passes, tell Claude: the four boxes are then ticked in a docs-only PR and the milestone is closed. If anything does not behave as written, say what you saw; it is fixed before the box is ticked.

**Why this order / what to understand**

*Why a stock at all, when staff could keep granting by hand.* An organization will ask "how many have we used" in the first conversation, and its admin should be able to hand licences out without writing to support. The stock is also the place a payment will write to: when the payments milestone arrives, "bought 10 at Tier 2" becomes one call to `set_seat_pool`'s sibling, and nothing else changes.

*Why a licence, not a tier on the member.* A single `tier` column on the membership would be simpler today and wrong as soon as money is involved. A licence has a source (stock, purchase, by hand), a grantor, a date and a revocation: what a refund or a dispute needs. It also lets one person hold a personal licence and an organization's licence without the two getting mixed up.

*Why counted, not stored.* Storing "7 left" next to the licences means two places that can disagree. Counting the licences is one query and is always right.

*Why the lock.* Two admins give the last licence at the same instant. Both read "1 left", both give, and the organization has handed out more than it bought. Locking the organization's row makes the second wait and then see "0 left". It is the same shape as the join code and the people limit in Milestone 3, and the same fix.

*Why a join never fails because of the stock.* The person holding the invite did nothing wrong, and the admin can fix the stock afterwards. Turning them away would make the organization's bookkeeping the member's problem. *(Since the second part of this milestone the question no longer comes up: the licence is set aside when the invite or code is made, so the stock cannot be empty at the join.)*

---

## Milestone 4, second part — Licences set aside for invites and join codes

*Planned on 2026-11-13 from the founder's answers of that day (decision log). It changes two of the choices made while building Milestone 4, and it comes before payments because it changes how the stock is counted, which a purchase adds to.*

**Goal:** a licence promised by an invite or a join code is really there. It is set aside out of the organization's stock when the invite or the code is made, the page read before joining says it comes with one, and an invite that has not been used can be emailed again or moved to another address.

**Status (2026-11-13).** Code-complete and live: PR 0 the plan (#75), PR 1 `lc-set-aside` (#76) and PR 2 `lc-resend-move`, which wrote this paragraph. 1,315 tests. Licences are set aside, the page before joining says when one comes with the invite or code, the stock lines show what is set aside, the "joined without a licence" warning is gone, and an open invite can be emailed again or moved to another address, five emails at most. What remains is the founder's two live checks (the checklist is below; `06-backlog.md`, T-18). Nobody has tried it by hand on the live site yet.

**How it is run.** Merged on green without waiting for review, like Milestones 3 and 4 (decision log, 2026-11-13). The rules below marked *builder's call* were not asked one by one, because the founder asked for small choices to be made sensibly and listed; each can be overruled.

**The product rules** (the founder's, 2026-11-13, unless marked)

- **Setting aside.** When an admin makes an invite with a tier, one licence of that tier is set aside. When they make a join code with a tier, one is set aside for each person the code allows. If the stock does not have that many left, making it is refused, and the message says how many are left.
- **What "left" means now.** For each tier: the licences bought, less those given to members, less those set aside. A licence set aside cannot be given to someone else by hand.
- **Joining.** Whoever joins with that invite or code is given the licence that was set aside for them. Nobody joins without the licence they were promised any more, so the "joined without a licence" warning is removed.
- **Coming back.** A licence set aside returns to the stock when the invite is withdrawn or expires, when the code is switched off or expires (for the uses nobody took), and when the person an invite was sent to is erased.
- **Emailing an invite again.** An invite that can still be accepted can be emailed again to the same address.
- **Moving an invite.** It can instead be sent to a different address. The old link stops working, the new address gets a new link, and the licence set aside follows it: only the new address can accept.
- **Five emails.** An invite is emailed at most five times in all, counting the first, the repeats and the moves.
- **The page before joining.** It says so when the invite or code comes with a licence: "Joining makes you a member. This invite comes with a licence to take the survey for (organization)." ("This code comes with…" for a code.) Otherwise: "Joining makes you a member. To take the survey for (organization) you also need a licence from it, which it may give you later." The tier is not named.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

- Emailing an invite again keeps its link, so the earlier email still works. Moving it makes a new link. Either way the invite's 14 days start afresh when the email goes out, so what the email says ("works for 14 days") is true of every email. *As built:* if the mail server refuses the email, the days do not restart; a moved invite whose email could not be sent keeps the expiry date it had, which the page shows.
- Only an invite that can still be accepted can be emailed again or moved. One that has expired or been withdrawn is replaced by sending a new invite.
- Moving an invite does not use another of the organization's places: it is still one person being brought in. The cap of five emails is what stops the invite form being used to write to many strangers.
- The five counts emails the mail server accepted. A send it refused (as Amazon SES does in its sandbox) does not count, and the admin can still copy the link.
- The join and its licence now happen together or not at all. This replaces "a join never fails because of the stock": the stock can no longer be the reason, and if something unexpected goes wrong while giving the licence, the person is told to try again rather than let in without what the page promised.
- A member who comes back with an invite and already holds a licence they have not used keeps it and gets no second one (kept by the founder); the licence set aside for that invite returns to the stock.
- Staff can still lower a stock below what is given and set aside. Every promise already made is kept (the page then shows more given than bought), and nothing more can be given or set aside at that tier until it is back under.
- An invite or code made before this change that carries a tier is treated as if its licences had been set aside.
- The tier drop-downs on the invite and join code forms say how many of each tier are left.

**What you build**

- `apps/enterprises/services.py`: `seats_set_aside(enterprise)` (per tier: open invites with a tier, plus the unused uses of working codes with a tier), and `seat_summary` gains `set_aside` and takes it off `left`. `invite_by_email` and `create_code` refuse a tier whose stock cannot cover it, under the organization's lock (`create_code` now takes that lock). `resend_invite(invite, by, request)` and `move_invite(invite, email, by, request)`, both returning `(invite, sent)`. `joined_without_licence` is removed. `_announce_join` no longer swallows a listener's failure.
- `Invite.emails_sent` (a small number, 0 by default, in a new migration), raised each time the mail server accepts the invite's email; `MAX_INVITE_EMAILS = 5`.
- `apps/entitlements/services.py`: `give_seat_on_joining` gives the licence without asking the stock (it was set aside), and still gives nothing to someone who already holds one.
- Pages: the invites page gets "Email it again" and "Send to a different address" on each open invite, with "Emailed 2 of 5 times"; the stock lines on the dashboard and the Licences page say how many are set aside; the join confirmation page gets the new last sentence; the warning comes off the dashboard and the Licences page. The staff admin shows the set-aside number beside bought, given and left, and how many times an invite was emailed.

**Technical detail**

- Counted, never stored, like everything else about the stock: an invite's licence is set aside while the invite is "pending" (not accepted, not withdrawn, not expired, address not erased), and a code's are `max_uses - uses` while it is "active". Expiry therefore needs no job: the count simply stops including it.
- When someone joins, the same transaction makes the invite accepted (or the code's uses one higher) and creates the licence, so the number left does not move: one fewer set aside, one more given.
- The enterprises app still cannot import the licences app. It owns invites, codes and the stock numbers, so the set-aside count lives there, and the licences app keeps listening for `member_joined`.
- Emailing never happens while a lock is held. The count is raised first, under the invite's lock, and lowered again if the mail server refuses; two clicks at once therefore cannot send a sixth email.
- Moving an invite locks the organization, then the invite; checks the new address like a new invite (a valid address, not an active member's, no other open invite to it); then changes the address and the link together. The old link is simply unknown afterwards, so it reveals nothing, not even the new address.
- Erasure needs no new rule: erasing the person an open invite was sent to already empties its address, which makes it "erased" and returns its licence.

**Tests**

- Setting aside: an invite with a tier is refused when none is left and takes one off "left" when made; a code needs as many left as it allows; two admins promising the last licence at the same moment (threads) produce exactly one; a licence set aside cannot be given by hand.
- Returning: withdrawing, expiry, switching off, a code's unused uses, and erasure each put the licence back.
- Joining: by invite and by code the person gets the licence and "left" does not move; a returning member with an unused licence gets no second and the set-aside one returns; a failure while giving the licence undoes the join.
- Emailing again and moving: the link survives a repeat and dies on a move; the old address can no longer accept and the new one can; the sixth email is refused; a refused send is not counted; another organization's invite is "not found"; a member who is not an admin cannot do either.
- Pages: the two sentences on the join page; the stock lines; no warning anywhere.

**PR plan**

0. `lc-plan`: this section. Docs only.
1. `lc-set-aside`: the count, the refusals, the licence on joining, the join page's sentence, the stock lines, the warning removed; the Milestone 4 live checklist brought in line.
2. `lc-resend-move`: `Invite.emails_sent`, emailing again, moving, the cap of five, the invites page, the staff admin; docs synced.

**Done when**

- [ ] On the live site: with one Tier 2 licence left, an invite with a Tier 2 licence can be sent and a second is refused; the person who accepts has the licence at once; withdrawing an open one gives the licence back. *(Founder's live check, part E below.)*
- [ ] An open invite is emailed again, then moved to another address: the old link no longer works and the new one does. *(Founder's live check, part F below.)*
- [x] All tests pass, including every tenant isolation test. *(1,315 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,315 tests, including every tenant isolation test. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Both code PRs were checked by breaking the code on purpose and confirming a test fails: twelve breaks in PR 1 and fifteen in PR 2, all caught. Four tests run two requests at the same moment in threads: two admins promising the last licence, two people joining on a two-person code, two clicks on "Email it again" at the cap, and two invites moved to one address.

One run in a real browser at phone width, against a local server (PR 2): an admin sends an invite with a Tier 2 licence, sees "Emailed 1 of 5 times", emails it again (the link is unchanged), opens "Send it to a different address instead", moves it (a new link; the old one answers "That invite link is not valid."), sees "1 set aside for invites and join codes" on the Licences page, and is refused a join code for five people when one licence is left. Nothing was wider than the phone.

*Not covered by anything automated:* real email delivery, and the live site beyond `/health` answering 200 after each deploy. While Amazon SES is in its sandbox, a send to an address SES has not verified is refused; the page then says so and the invite's link is copied by hand. That path is tested, but it means the founder's live check will show "we could not send the email" for most addresses until SES is out of the sandbox (`06-backlog.md`, T-4).

**Live checklist (for the founder)**

Run it after the Milestone 4 checklist above, in the same organization, or in any organization whose stock you can set. You need window 1 (your superuser login) and window 2 (a private window), and two accounts with verified email addresses that are not members yet. Nothing here needs SSH, the AWS console or GitHub.

*Part E: a licence is set aside for an invite (box 1).*
1. Django admin, the organization, "Licence stock…": set "Tier 2 licences bought" so that exactly one is left (the organization's Licences page should read "1 of N Tier 2 licences left").
2. Window 1: "Invites". Type the first person's address, choose "Tier 2 licence (1 left)" and press "Send invite". The invite's line ends "Comes with a Tier 2 licence". The Licences page now reads "0 of N Tier 2 licences left · 1 set aside for invites and join codes", and beside every member the Tier 2 choice has gone from "Give licence".
3. "Invites" again: the drop-down now says "Tier 2 licence (none left)". Send a second invite, to any other address, with Tier 2: it is refused, "Your stock has no Tier 2 licences left".
4. Window 2, logged in as the first person: open the invite's link (from the email, or "Copy link"). Above the button the page says "This invite comes with a licence to take the survey for (your organization)." Join. The message says you have a licence. Window 1: the Licences page shows that person with a Tier 2 licence, "Not used yet", and nothing set aside.
5. To see a licence come back: Django admin, raise "Tier 2 licences bought" by one; send an invite with Tier 2 to any address (the Licences page says 1 set aside); press "Withdraw invite"; the Licences page says 1 left and nothing set aside.

*Part F: email an invite again, then move it (box 2).*
1. Window 1: "Invites". Send an invite to the second person's address (with or without a licence). Its line says "Emailed 1 of 5 times." (or "Emailed 0 of 5 times." if the page warned that the email could not be sent: a refused email is not counted). Copy its link and keep it.
2. Press "Email it again". The page says the invite was emailed again (or that it could not be sent), and the link in the box is the same as before.
3. Open "Send it to a different address instead", type an address of your own that has no account in this organization, and press "Move the invite". The page says the invite now goes to the new address and that the old link no longer works. The link in the box has changed.
4. Window 2: paste the old link you kept. It answers "That invite link is not valid."
5. Window 2, logged in with an account that has verified the new address: open the new link and join. It works. (An account that has only the old address is told the invite was sent to another address.)

When both parts pass, tell Claude: the two boxes are ticked in a docs-only PR.

---

## Milestone 4b — Payments

*Moved here on 2026-11-13 by the founder, from Phase 3, to follow Milestone 4. The founder answered the basics the same day, and this plan was written from them (PR 0). The provider is Stripe, on test keys.*

**Goal:** a person can buy a licence and pay to upgrade one, and an organization's admin can buy licences into its stock, without staff typing anything; staff can refund from the Django admin; and every payment leaves a record that holds no personal identity.

**Status (2026-11-13).** Code-complete and deployed: PR 0 the plan (#78), PR 1 the models and the Stripe wrapper (#79), PR 2 starting a purchase and giving what was paid for (#80), PR 3 the buy pages (#81), PR 4 refunds (#82), and PR 5, these docs. 1,547 tests. **Buying is open on the live site on Stripe's test keys, as far as can be told from outside:** the founder did the five steps under "What the founder does" on 2026-11-13, and the secrets had reached the server by 2:09pm PST that day (an unsigned request to the webhook is answered "Bad signature" where it used to be answered "Not set up"). Nobody has yet opened the buy page to see that it no longer says "Buying online is not open yet"; that is the first step of the live checklist. **Nothing has been run against Stripe itself:** in every test Stripe is played by a stand-in, so the first real payment page will be the founder's, on test keys, with the live checklist below (`06-backlog.md`, T-22). The builder's calls are under "Smaller rules" and wait for the founder's word.

**How this milestone is run** (founder, 2026-11-13). As Milestones 3 and 4 were: each PR is merged once CI is green and checked on the live site, with a summary after each. The founder is away while it is built and asked for product choices to be sent to their phone. None was needed for this plan: the basics and the defaults below were all accepted beforehand ("those defaults are fine"), and the smaller calls are listed to be overruled.

**Why it moved.** While deciding who should type an organization's stock into the admin, the founder asked why anyone types it at all. The answer was that the site cannot take payments; the founder's decision was to build payments next rather than later.

**The product rules, as decided by the founder on 2026-11-13**

- **Provider.** Stripe, "for now", through Stripe's own hosted payment page (Stripe Checkout): the person is sent to Stripe to pay and comes back. Accelerare never sees or stores a card number. Test keys until the founder has tried a purchase and says to switch to real ones.
- **Open to everyone.** The buy pages are open on the live site even while Stripe is on test keys ("treat it like it's live with customers"). On test keys only Stripe's test cards work and no money moves.
- **Prices.** $1, $2 and $3 for Tier 1, 2 and 3, as placeholders. They live in the database, staff change them in the Django admin, and the amount is sent to Stripe with each purchase, so a price change needs no code and nothing set up in Stripe. No volume price: a large deal is still invoiced by hand and staff type the stock.
- **A person** buys one licence per purchase, at the tier they choose.
- **An upgrade** raises a personal licence's tier and charges the difference between the two prices. It works before or after the survey is taken (afterwards it is how someone sees more of their results).
- **An organization.** Any of its admins buys a number of licences of one tier per purchase. They go into the stock, and from there everything is as in Milestone 4. A licence already in an organization's stock cannot be upgraded by paying, in this first version.
- **Refunds.** Only for a licence that has not been used, within 30 days of the payment. Staff do it with a Refund button in the Django admin: one step refunds through Stripe and takes the licence back, and leaves a history line. For an organization, only licences still in its stock (not given to a member, not set aside) can be refunded. Only superusers can refund.
- **Sales tax.** None is collected at first. Switching on Stripe's automatic tax later is a setting, not a code change (`06-backlog.md`, D-20: review with an accountant before real prices).
- **Receipts and invoices.** A person gets Stripe's emailed receipt. An organization's purchase also gets a numbered invoice from Stripe.
- **The record.** Every payment is a row that holds amounts, dates, the tier and Stripe's references, and no name, email or card detail. Erasing a person never removes or changes it.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

- Buying needs a verified email, like everything else that matters on the site.
- A person may buy a licence while they still hold an unused one; nothing stops them holding two. Each is one attempt.
- Any personal licence that is not withdrawn can be upgraded, including one staff granted by hand. A licence held through an organization cannot.
- "Not used" for a refund means the survey has not been started on it at all. Once the first page has been begun, the Refund button refuses.
- An upgrade can be refunded on its own (the licence goes back down a tier). The original purchase can be refunded only after any upgrade on top of it has been.
- An organization buys at most 1,000 licences in one purchase.
- If Stripe is not set up (no key), the buy pages say buying online is not open yet and how to reach Accelerare; nothing else on the site changes.
- The licence appears as soon as the person is back from Stripe: the page they return to asks Stripe whether the payment went through, and Stripe's own message to the site does the same job if they close the browser first. Either way the licence is given exactly once.
- A refund made in Stripe's own dashboard instead of the Django admin is noticed. The site takes the licence back if the rules above allow it; if they do not (the survey was started, the licences were given out), the payment is marked "needs attention" in the admin with the reason, and nothing is taken from anyone automatically.
- A payment that arrives for something that can no longer be given (the account was erased while paying, the licence was withdrawn before an upgrade was paid) is kept, marked "needs attention", and staff refund it.
- Support staff can see prices and payments in the Django admin and change neither. Superusers change prices and refund.
- Not built in this version, on purpose: a page listing a person's or an organization's past payments (Stripe emails the receipt), saved cards, subscriptions, coupons, and handling of a disputed charge (Stripe emails the founder; staff then withdraw the licence by hand).

**What you build**

- A new app, `apps/payments/` (installed after `entitlements` and before `funnel`; the apps still depend one way: `accounts` ← `enterprises` ← `entitlements` ← `payments`, with `responses` last and importing none of it).
- `apps/payments/models.py`: `Price` (tier, unique; `amount_cents`), three rows made by a data migration at 100, 200 and 300. `Purchase`: `kind` (personal, upgrade, stock), `status` (pending, paid, part refunded, refunded, failed), `tier`, `from_tier` (upgrades only), `quantity`, `unit_amount_cents`, `amount_cents`, `currency`, `refunded_cents`, `refunded_quantity`, `stripe_session_id` (unique), `stripe_payment_intent_id`, `stripe_invoice_id`, `needs_attention` and a plain-words `note`, `created_at`, `paid_at`, and three links that are all emptied rather than followed if what they point at goes: `buyer` (the account that pressed Buy), `entitlement` (the licence bought or upgraded) and `enterprise` (stock purchases; kept, organizations are never deleted). `Refund`: the purchase, `amount_cents`, `quantity`, `stripe_refund_id`, `made_by`, `created_at`. No `__str__` holds an email or a name.
- `apps/payments/stripe_api.py`: the only file that talks to Stripe: `create_checkout`, `get_checkout`, `refund_payment`, `read_event`. Each returns plain values. Everything else in the app, and every test, sees Stripe only through these four functions.
- `apps/payments/services.py`: `prices()`, `upgrade_cost(entitlement, tier)`, `start_personal(account, tier, request)`, `start_upgrade(account, entitlement, tier, request)`, `start_stock(admin_membership, tier, quantity, request)` (each makes a pending `Purchase`, opens a Stripe Checkout and returns the address to send the person to), `fulfil(checkout)` (gives what was paid for, once), `refund(purchase, by, quantity=None)` and `record_outside_refund(charge)`. A refused action raises `Refused` with plain words for the page.
- `apps/enterprises/services.py`: `add_seats(enterprise, tier, quantity)` and `remove_seats(enterprise, tier, quantity)`, beside `set_seat_pool`, under the organization's lock. `remove_seats` refuses to take more than are left.
- Pages: `/buy/` (the three tiers with their prices and a Buy button each; under them the person's own licences with "Upgrade to Tier N" buttons), `/buy/done/` and `/buy/cancelled/` (where Stripe sends the person back), and for an organization's admin `/organizations/<slug>/licences/buy/` (tier and number). Links to them from "My surveys", from the "You need a licence" notice, from the result page (to upgrade), and from the organization's Licences page and dashboard, replacing "Accelerare adds licences by hand for now".
- `/payments/stripe/webhook/`: where Stripe tells the site that a payment went through (`checkout.session.completed`) or was refunded (`charge.refunded`). It checks Stripe's signature on every message and ignores anything else.
- Django admin (the hub): "Prices" (three rows; superusers change the amount, typed in dollars), "Payments" (read-only list with filters for status, kind and "needs attention", searchable by Stripe's references and the organization's name; the page of one payment has a "Refund…" button for superusers, which asks first and says exactly what will happen) and its refunds listed beneath. Every refund writes a history line that names nobody.
- Settings: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` and `STRIPE_AUTOMATIC_TAX`, all optional everywhere, so the order of deploys and keys does not matter. `.env.example`, `NOTES.md`'s porting checklist and the runbook gain them.

**Technical detail**

- *Nothing is trusted from the browser.* The Buy button sends only a tier (and a number, for an organization). The price is read from the database on the server, the `Purchase` row is written first, and Stripe is told the amount by the server. The page the person returns to carries only Stripe's session id, which is looked up among that person's own purchases and then checked with Stripe.
- *Given exactly once.* `fulfil` locks the `Purchase` row and does nothing unless it is still pending, so the return page and Stripe's message can both arrive, in either order or twice each, and the licence is given once. It also checks that Stripe says "paid" and that the amount and currency are the ones on the row.
- *What fulfilling does.* Personal: `grant_individual(person, tier, "purchase")`, which records the funnel event. Upgrade: `change_tier`, only if the licence is still active and still at the tier the upgrade started from. Stock: `add_seats`, under the organization's lock, which also raises the people limit as Milestone 4 decided. Anything that cannot be given marks the row "needs attention" and gives nothing.
- *Refunding.* Inside one transaction: lock the purchase, check the rules, take back what was sold (`revoke`, `change_tier` back down, or `remove_seats`), then ask Stripe for the refund. If Stripe refuses, the transaction is undone and nothing was taken back. Stripe is given a key that makes a repeated request the same refund, not a second one.
- *Stripe's messages.* The body is checked against `STRIPE_WEBHOOK_SECRET` with Stripe's library before anything is read. A message of a kind the site does not use is answered "fine" and ignored. A failure while handling one answers with an error so that Stripe sends it again, and the handlers are safe to run twice. Nothing from a message is written to a log: it holds an email address.
- *Erasure.* A `Purchase` holds no identity. Deleting an account empties `buyer`; deleting its licences empties `entitlement`; the amounts, dates and Stripe's references stay. Stripe itself keeps the email it sent the receipt to; that is Stripe's record as the payment processor, and belongs on the privacy lawyer's list (`06-backlog.md`, D-7).
- *Sentry already receives no request bodies and no local variables*, so a failed webhook does not send Stripe's message there.
- *Tax.* `STRIPE_AUTOMATIC_TAX` set to true adds Stripe's automatic tax to every checkout. Turning it on also needs tax registration set up in Stripe's dashboard, which is the accountant's question (D-20).
- *Money is whole cents in an integer column,* never a decimal with fractions, and never worked out in the browser.

**What the founder does** **[console]** (Stripe's dashboard and the AWS console. *Done by the founder on 2026-11-13, in a Stripe sandbox, which is Stripe's name for test mode.*)

1. A Stripe account, in test mode. From Developers, API keys: the secret key (`sk_test_…`).
2. That key into AWS Parameter Store as `/survey/prod/STRIPE_SECRET_KEY` (SecureString), and into the laptop's `.env` as `STRIPE_SECRET_KEY`.
3. In Stripe, Developers, Webhooks: add the address `https://app.theaccelerare.com/payments/stripe/webhook/` with the events `checkout.session.completed` and `charge.refunded`. Its signing secret (`whsec_…`) into Parameter Store as `/survey/prod/STRIPE_WEBHOOK_SECRET`.
4. The next deploy picks both up (`deploy/render_env.py` turns every parameter under `/survey/prod/` into a server variable). A docs-only merge does not deploy, so it takes a code merge or "Run workflow" on the Deploy action.
5. In Stripe, Settings, Emails: switch on receipts for successful payments. Stripe does not email receipts in test mode; that is checked when real keys go in.

**Tests**

- Prices: three rows after migrating; a superuser changes one in the admin and the buy page shows it; Support staff cannot.
- Starting: each of the three kinds writes one pending row with the server's price and sends Stripe the same amount; an unverified account, a tier that does not exist, a number out of range, someone else's licence, a licence held through an organization, an upgrade to the same or a lower tier, and a member who is not an admin are all refused before Stripe is called; with no key the pages say buying is not open.
- Fulfilling: each kind gives what was paid for; twice, or from the return page and the webhook at the same moment (threads), gives it once; "unpaid" gives nothing; a wrong amount gives nothing and marks the row; an upgrade whose licence changed meanwhile is marked and gives nothing; a stock purchase raises the people limit.
- The webhook: a message with a bad signature or none is refused; a good one fulfils; a kind the site does not use is ignored; without the secret set it answers "not set up".
- Refunds: an unused personal licence within 30 days is refunded and withdrawn; a started one, one past 30 days, and one with an upgrade on top are refused; an upgrade's refund puts the tier back; a stock refund takes only what is left and refuses more; if Stripe refuses, nothing is taken back; a refund made in Stripe's dashboard is noticed, taken back when allowed and marked when not; only a superuser sees the button.
- Tenant isolation, written before the page: organization A's admin cannot open B's buy page or buy into B's stock (404), and a member who is not an admin cannot open the page.
- Erasure: erasing a buyer both ways keeps every `Purchase` and `Refund` row with its amounts.
- Nothing personal: no payment page, admin label, history line or log line contains an email or a name.

**Built as planned, with these differences** (each is also in its PR's description)

- *`Purchase.given_at`* (PR 4) was not in the plan. It records when what was paid for was given. A paid row without it is money that came in for nothing, and the Refund button then refunds it whole, with nothing to take back and no 30-day limit.
- *Coming back without paying* returns the person to the buy page they left, not to "My surveys".
- *The names in `stripe_api.py`* are `create_checkout`, `get_checkout`, `refund_payment`, `read_event`, and two small readers of a message, `checkout_in` and `charge_in`.
- *The page that asks before a refund* shows the same refusal the button would give, by trying the take-back in a transaction that is always undone (`refund_preview`).
- *An organization's member who needs a licence* is told to ask one of its admins; only a personal licence can be bought by the person themselves.
- *Not built:* an email to the person when their payment is refunded (Stripe sends its own), and any funnel event for an organization's purchase (the payment record is the count).

**PR plan** (one branch and one pull request each, in this order; all merged)

0. `m4b-plan` (#78): this section; T-17 closed and T-21 (the founder's Stripe steps) opened in the backlog. Docs only.
1. `m4b-payments-models` (#79): the app, its three models and migrations, the prices, the three settings, `stripe_api.py`, the read-only admin with editable prices, `add_seats` and `remove_seats`, erasure tests.
2. `m4b-checkout` (#80): the three `start_…` services, `fulfil`, the webhook, the return and cancelled pages.
3. `m4b-buy-pages` (#81): the personal and organization buy pages and every link to them; isolation tests first.
4. `m4b-refunds` (#82): the Refund button, `refund`, refunds made in Stripe's dashboard, "needs attention".
5. `m4b-docs-live-checks`: docs synced with what was built, and the founder's live checklist. Docs only.

**Done when**

*The first three boxes are the founder's live checks, with Stripe's test card.*

- [ ] On the live site, with the test keys in place: a person buys a Tier 1 licence with Stripe's test card `4242 4242 4242 4242`, is brought back, and can start the survey at once; then upgrades it to Tier 2 and pays only the difference.
- [ ] An organization's admin buys three Tier 2 licences; the stock and the people limit both go up by three; the payment is in the Django admin with no name or email on it.
- [ ] A superuser refunds an unused licence from the Django admin: the money goes back in Stripe's dashboard and the licence is withdrawn; a used one is refused.
- [x] All tests pass, including every tenant isolation test. *(1,547 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,547 tests, including every tenant isolation test (which now runs with buying open, so a buy form sent to the wrong organization would really write a payment row and be caught). `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Each code PR was checked by breaking the code on purpose: thirteen breaks in PR 1, seventeen in PR 2, ten in PR 3 and seventeen in PR 4. Fifty-three were caught by a test. The other four are places where a page's own check was removed and the service underneath still refused. Four tests run requests at the same moment in threads: the return page and Stripe's message together (one licence), a stock purchase confirmed twice (added once), and two staff refunding at once (one refund). One test found a real fault before the first commit: a database rule that let "an upgrade from nothing" through (NOTES 2026-11-13).

One run in a real browser at phone width, against a local server (PR 3): a person opens "My surveys", goes to the buy page, buys a Tier 2 licence, comes back and sees it ready; upgrades a Tier 1 licence to Tier 3 and comes back; an organization's admin opens "Buy licences", starts a purchase, cancels (back on the same page, "Nothing was charged"), buys three Tier 2 licences and comes back to "3 of 3 Tier 2 licences left"; and with no Stripe key both pages say buying is not open. Nothing was wider than the phone. Stripe's own page was a stand-in in that run.

*Not covered by anything automated, and so not verified at all:* every conversation with Stripe itself. The file that talks to Stripe has been run only against a stand-in for Stripe's library (its signature check is the exception: that is Stripe's real code, run on messages the tests sign themselves). Whether a real payment page opens, takes the test card, comes back, and whether Stripe's message reaches the site and is accepted, will first be seen in the founder's live checklist below. If any of it fails, the place to look is `apps/payments/stripe_api.py`, and Sentry will have the error. The two admin pages for a refund were tested through requests, not looked at in a browser.

**Live checklist (for the founder)**

The five steps under "What the founder does" were done on 2026-11-13. Run this on the live site, on Stripe's **test** keys: no real money moves. You need window 1 (your superuser login, also for the Django admin), window 2 (a private window) with an ordinary account whose email is verified, an organization that account 1 is an admin of, and Stripe's dashboard open in test mode. Stripe's test card is `4242 4242 4242 4242`, with any date in the future, any three digits and any postcode. Nothing here needs SSH or GitHub.

*Part A: a person buys a licence, then upgrades it (box 1).*
1. Window 2: "My surveys". The Personal box says "Taking the survey needs a licence" with a "Buy a licence" button. Press it. The page lists Tier 1, 2 and 3 at $1.00, $2.00 and $3.00. (If it says "Buying online is not open yet", the secret key has not reached the server: check that `/survey/prod/STRIPE_SECRET_KEY` is in Parameter Store under exactly that name, then tell Claude, because it takes a deploy that is not docs-only to bring it in.)
2. Press "Buy for $1.00". You are on Stripe's page, which shows "Tier 1 licence" and $1.00. Pay with the test card.
3. You are brought back to "My surveys" with "Thank you. Your Tier 1 licence is ready." and "You have 1 unused licence", with a Start button.
4. "Buy a licence, or upgrade one you have". Under "Your licences" the Tier 1 licence has "Upgrade to Tier 2 for $1.00" and "Upgrade to Tier 3 for $2.00". Press the first and pay $1.00 on Stripe's page. Back on "My surveys": "Thank you. Your licence is now Tier 2."
5. Window 1: Django admin, "Payments". Two payments, "1 x Tier 1" for $1.00 and "Tier 1 to Tier 2" for $1.00, both "Paid". Neither line shows a name or an email.
6. Stripe's dashboard, Payments: the same two payments. Developers, Webhooks, your endpoint: the `checkout.session.completed` messages show as delivered.

*Part B: an organization buys licences (box 2).*
1. Window 1: your organization's page. Note what "Bring people in" says about places, and what the Licences box says. Press "Buy licences".
2. Choose "Tier 2 licence, $2.00 each", type 3, "Continue to payment". Stripe's page shows 3 at $2.00 and a total of $6.00. Pay with the test card.
3. You are brought back to the Licences page: "Thank you. 3 Tier 2 licences have been added to (your organization)'s stock." The Tier 2 line has three more than before, and the organization's page has three more places.
4. Django admin, "Payments": "3 x Tier 2", $6.00, "Paid", with the organization named and nobody else.
5. Start again from "Buy licences", and on Stripe's page press the back arrow instead of paying. You are back on "Buy licences" with "Nothing was charged."

*Part C: a refund (box 3).*
1. Django admin, "Payments", open the organization's payment. Press "Refund…" at the top right, beside History. The page says the licences refunded are taken out of the stock and $2.00 goes back for each. Type 1 and press "Yes, refund through Stripe".
2. The payment now reads "Partly refunded" and "$6.00 ($2.00 refunded)". The organization's Tier 2 stock is one lower. In Stripe's dashboard the payment shows a $2.00 refund. The payment's History says who refunded it.
3. Window 2: start the survey on the personal licence and answer the first page. Window 1: open the "1 x Tier 1" payment, "Refund…". It says the payment cannot be refunded here, because the survey on the licence has been started, and there is no refund button. (It would also be refused for the upgrade on top of it.)
4. To see a personal refund work: in window 2 buy another Tier 3 licence and do not start it; in window 1 refund that payment. Window 2: "My surveys" no longer offers that licence.

*Afterwards.* Stripe does not email receipts in test mode, so the receipt and the organization's invoice are checked when real keys go in. Tell Claude what you saw: the three boxes are then ticked in a docs-only PR. Real keys go in only when you say so, and after the accountant's answer on tax (`06-backlog.md`, D-20).

**Why this order / what to understand**

*Why Stripe's hosted page.* Taking card numbers on your own page makes you responsible for keeping them safe, with audits to prove it. Sending the person to Stripe's page means the card never touches this site. The cost is that the person leaves for a moment and comes back, which is what the return page and the webhook are for.

*Why two ways of hearing "it was paid".* The person's browser coming back is fast but unreliable: they may close the tab on Stripe's page the instant they have paid. Stripe's own message to the site (a "webhook") is reliable but can be a few seconds late. Using both means the licence is there when they land and is still given if they never land. The price of having two is that both may arrive, which is why giving the licence is written to be safe to do twice.

*Why the row is written before the money moves.* If the site only learned of a purchase when Stripe said "paid", it would have to trust what Stripe's message said was bought. Writing a pending row first, with the server's own price, means the message only has to say which row was paid.

*Why prices are in the database.* The founder will change them, more than once, and should not need a developer or Stripe's dashboard to do it.

*Why the record has no name in it.* Accounting records are kept for years; a person can ask to be erased tomorrow. Keeping the two apart means neither rule has to bend.

---

## Milestone 5 — Background jobs, possible duplicates, audit log

*Re-planned on 2026-11-13. This section replaces the original one, which no longer fitted what has been decided and built since October. What changed, and why, is under "What the re-plan corrects" and in the decision log.*

**Goal:** work that is slow or may fail runs outside web requests, in a background worker; a member is emailed when they are given a licence; accounts that look like the same person are brought to a superuser, who links them or says they are different, and can undo a link; and what staff and organization admins do is kept in one audit log.

**Status (2026-11-13).** Code-complete and deployed: PR 0 the re-plan (#84), PR 1 the queue and the worker (#85), PR 2 the licence email (#86), PR 3 the audit log (#87), PR 4 possible duplicates and linking (#88), PR 5 the match box (#89), PR 6 the results seam (#90), and PR 7, these docs. 1,786 tests. The server runs a third container, the worker, since PR 1; every deploy since has ended with a check that it starts, and `/health/worker` answers "ok". **Nobody has tried any of it by hand on the live site**, and the licence email has never been sent by the live worker: what remains is the founder's live checklist (below; `06-backlog.md`, T-24), which the first four "Done when" boxes wait for. What was built differently from the plan is under "As built"; the builder's calls are under "Smaller rules" and wait for the founder's word.

**How this milestone is run** (founder, 2026-11-13). As Milestones 3, 4 and 4b were: merged on green without waiting for review, a summary after each PR. The founder is away while it is built. The three defaults put to them beforehand were accepted ("those defaults are fine") and are the first three product rules below; the builder's further calls are listed to be overruled.

**What the re-plan corrects**

- *A box that contradicted the plan.* "Done when" said "two test accounts with the same verified email become one person". The plan's own text, and the decision of 2026-10-09, say there is no verified-email rule: a verified email has one owner, and a second claim is turned away with the recovery page, never linked. The box is replaced.
- *Nothing links accounts automatically.* The only automatic rule left was "same verified phone", and no phone can be verified until SMS exists (`06-backlog.md`, L-7). So in this milestone every link is made by a superuser confirming a possible duplicate. The verified-phone rule is kept as a rule that finds nothing today.
- *The invite email stays where it is.* The original plan moved it to the worker. Since Milestone 3 the invite page tells the admin at once whether the email went and offers the link to copy if it did not, and since Milestone 4's second part it counts the emails an invite has had. Sending in the background would take that answer away. The worker's first email is a new one instead: "you have been given a licence".
- *Staff actions are audited without changing every service.* The Django admin already writes a history line for each staff action. The audit log copies each of those lines as it is written, and the services record what organization admins do, which nothing recorded before.
- *Bounces and complaints from Amazon SES* need work in the AWS console (an SNS topic), so they become a backlog task (T-23), not part of this build.

**The product rules**

- **A member is emailed when an admin gives them a licence** (founder's default, accepted 2026-11-13). The email says which organization and that the survey can be started; it does not name the tier. It is sent in the background: the admin's page does not wait for it.
- **Only superusers review possible duplicates** (founder's default, accepted). Support staff do not see them.
- **Bounce and complaint events from SES are a backlog task** (founder's default, accepted).
- **When two accounts look like the same person,** nothing happens to either. A "possible duplicate" appears in the Django admin for a superuser, saying what the two have in common. Neither person is told and nothing changes for them.
- **What makes two accounts look alike** (from the architecture doc): the same phone number; the same full name when both belong to an organization; and, from the survey's own question, an email address or phone number the person typed to help find their earlier results that belongs to another account.
- **A superuser decides.** "Same person" links the two: both logins keep working, and personal licences are shared between them, because a licence belongs to the person. "Different people" closes it and it is not raised again. A link can be undone.
- **A possible repeat.** A survey taken for an organization is marked "possible repeat" for that organization's admins, as the join page already promises, when the person said they had taken the survey before, or when they (through this login or one linked to it) have an earlier submitted survey. An unreviewed possible duplicate marks nothing.
- **The match box.** After answering "Yes, I have taken this survey before", the person may type an email address or phone number that would help find their earlier results. It is optional, and nothing depends on it. It is used once, to look for another account, and then removed. *(As built it is removed whether or not it led to a possible duplicate; the plan kept it when it did. See "As built".)* Only superusers ever see it. Erasing the person removes it.
- **The audit log** keeps who did what and when: every staff action in the Django admin from the day it is deployed, and what organization admins do (invites, join codes, members, licences, purchases). It holds no name, email or answer, only numbers and plain facts. Superusers read it in the Django admin.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

- The two accounts of a possible duplicate are linked by moving the newer account onto the older account's person. Personal licences of both then belong to that one person. Each login still sees only its own surveys in "My surveys".
- *Changed while building.* Undoing a link gives the newer account its own person again, and each licence goes by two facts: a licence either login has used stays with the login whose survey is on it, and an unused one goes to the login it was granted to or bought by (`Entitlement.granted_to`, new, and filled in for every licence that existed). The plan said a licence granted by hand while linked would stay with the first account; since staff choose a login when they grant, that caveat is gone.
- *New while building.* A person has two linked logins at most. A login that is already linked cannot be linked to a third; the superuser is told why. With two at most, every link is one row and "undo" is exact (`06-backlog.md`, L-11).
- *New while building.* A link that was undone can be made again. A pair closed as "different people" cannot be reopened.
- *New while building.* The look for duplicates runs, in the background, when an email is verified, a phone or a name is changed, someone joins an organization, a survey is submitted, or the match box is filled in. Accounts that existed before this was deployed are looked at the next time one of those happens to them, or when a superuser selects them on the Accounts page of the Django admin and chooses "Look for possible duplicates of the selected accounts" (built on 2026-11-13 as T-25).
- *New while building.* The same-phone rule counts a phone whether or not it is verified, because no phone can be verified yet. The match box counts an email address only if its owner has verified it.
- The same-name rule looks only at accounts that both belong to some organization (the same one or different ones), and compares the full name after lowercasing, removing accents and tidying spaces. No "close enough" matching.
- A pair that was looked at and closed as "different people" is not raised again by any rule.
- The licence email goes to the address the organization knows the member by (the invited address, else their login address), like every other place an organization's admin sees a member. Joining with an invite or code that comes with a licence sends no email: the person has just been told on the page.
- A job is tried five times, waiting longer each time (2, 4, 8 and 16 minutes), then marked failed and shown to staff, who can run it again. A failed job stops nothing else.
- A job's record holds no personal data: an email job stores the number of the licence, never the address, and looks the address up when it runs. If the person has been erased by then, it does nothing.
- If the worker is not running, nothing breaks for people using the site: the licence is still given, the survey still submits. Emails and checks wait in the queue and run when it is back. The Django admin's Jobs page says how long the oldest job has waited.
- `/health` stays exactly as it is. A second address, `/health/worker`, answers "ok", or "behind" when a job has waited more than ten minutes, so the uptime checker can watch the worker too (`06-backlog.md`, T-26: the checker exists since 2026-11-13 and watches `/health` only so far).
- *New while building.* The audit log shows people by account number only ("Account #7", with a link to the account). An admin history line is copied without its label for the object, which can be an email address. "Email it again" on an invite is recorded after the attempt, with whether the mail server took it; everything else is recorded inside the action's own transaction.
- *New while building.* When a superuser decides a possible duplicate, the audit log gets two rows: the fact ("accounts.linked", with the two account numbers and the licences that moved) and the copy of the admin's history line. Erasing an account has done the same since PR 3.
- The results seam from the "Phase 2 stub" below (a `Result` table and a `compute_result` that returns nothing) is built here as the last small PR, so that the algorithm, when it comes, has somewhere to go.

**What you build**

- `apps/jobs/` (installed after `funnel`; it imports no other app, like `funnel`): `Job` (kind, payload JSON, status queued/running/done/failed, attempts, max_attempts 5, run_after, locked_at, last_error, created_at, finished_at). `jobs.enqueue(kind, payload, run_after=None)`; a registry, `@job("kind")`, mapping a kind to the function that does it (each app registers its own handlers in its `jobs.py`, loaded when Django starts); `jobs.run_due()` runs what is due once (the worker's loop and the tests both call it).
- `apps/jobs/management/commands/run_worker.py`: claims the oldest due job with `select_for_update(skip_locked=True)`, marks it running, commits, runs it, then marks it done, or queued again for later, or failed. Sleeps a second when idle. On `SIGTERM` it finishes the job in hand and exits. A job left "running" for ten minutes (the worker died) is queued again. `--once` runs what is due and exits.
- `deploy/docker-compose.yml`: a `worker` service, the same image as `web`, running `python manage.py run_worker`. `deploy.sh` needs no change: `docker compose up -d` starts it.
- Django admin "Jobs": read-only list with status and kind filters, the oldest waiting job's age at the top, "Run again" for a failed job and "Queue a test job" (superusers); Support staff can look.
- The licence email: `templates/entitlements/email/licence_given_*.txt`, queued by `assign_seat` inside its transaction, sent by a `send_licence_email` job.
- `apps/audit/` (imports only `accounts`): `AuditLog` (actor, emptied if that account is deleted; action; target_type; target_id; detail JSON; at). `audit.record(actor, action, target, **detail)`. A receiver that copies every Django admin history line into it. Calls from the organization admins' services, inside their transactions. `erase_account` writes a row. Django admin "Audit log": read-only, filters by action and date, searchable by target; superusers only.
- `apps/matching/` (after `entitlements`; it imports `accounts`, `enterprises` and `entitlements`): `MatchCandidate` (account_a, account_b with a < b, signals JSON, status flagged/confirmed/rejected/unlinked, resolved_by, resolved_at, what was moved when linking; unique on the pair). `rules.py`: one function per rule and a `RULES` list. `services.py`: `run_for_account(account)`, `confirm(candidate, by)`, `reject(candidate, by)`, `unlink(candidate, by)`. A `run_matching` job, queued when an email is verified and when a survey is submitted. Django admin "Possible duplicates": flagged first, each action behind a page that says what will happen; superusers only.
- `Entitlement.granted_to` (the account a personal licence was granted to or bought by; empty for older ones), so that undoing a link knows whose a licence is.
- `apps/responses`: `Response.possible_repeat` is set on submission. `Response.match_hint` (text, emptied after use) and the optional box on the start page under "Yes".
- `apps/results/`: `Result`, `compute_result` returning `None`, a `compute_result` job queued on submission, `recompute_results`.

**As built** (what differs from the list above)

- `apps/jobs`: each app's handlers are in a file called `job_handlers.py` (the list above says `jobs.py`). `deploy.sh` did change: it ends with a "Worker check" that asks the worker's container to run what is due and stop, so a worker that cannot start fails the deploy loudly.
- `apps/audit` imports no other app (the list says it imports `accounts`), so `accounts` itself can write to it when erasing. Its actor is a plain link to the account table, emptied if the account is deleted.
- `apps/matching` imports `accounts`, `entitlements`, `audit` and `jobs`, and reaches memberships and responses through an account's reverse names. `MatchCandidate` keeps the person the newer login had to itself (`old_person`) rather than a list of what was moved; the audit row holds the list. The job is called `look_for_duplicates`, and `accounts.services.look_for_duplicates_later(account)` queues it.
- `Response.possible_repeat` is worked out on submission and again for both logins whenever a link is made or undone (the matching app sends a signal the responses app listens to).
- `apps/results` imports no other app, so the `compute_result` job and `recompute_results` are in the responses app. See the Phase 2 stub below.
- A new optional setting, `SITE_URL`, for links in emails the worker sends; the server works it out from its host name.

**Technical detail**

- *Queued in the same transaction.* `enqueue` writes the job row in the caller's transaction. If giving the licence is undone, the job row goes with it, so there is never an email for something that did not happen.
- *At least once.* A worker can die after doing a job and before recording it. The job then runs again, so every handler must be safe to run twice. Looking for duplicates is (the pair is unique). Working out a result is. An email is not, and there a second copy after a crash is accepted.
- *`skip_locked`* is what lets a second worker run safely later; there is one today.
- *What a job may store.* `last_error` holds the kind of error only, never the mail server's reply, which can quote an address. The log line that tells Sentry is written the same way.
- *Linking.* `confirm` locks both accounts, moves account B onto account A's person, moves B's old person's licences to A's person, records their numbers on the candidate, and marks the old person `merged_into`. `unlink` puts B back on its old person and moves back those licences that are not revoked, plus any whose `granted_to` is B. Both write audit rows. Nothing about responses changes: a response belongs to an account.
- *A link never happens on an unverified signal alone.* Rules only ever create a flagged candidate; `confirm` is the only thing that links, and only a superuser can call it. A test asserts that running every rule changes no account's person.
- *Audit rows are written in the same transaction as the action,* so there is never a record of something that was undone, nor an action without its record. The copy of an admin history line is written in the same database save as the line itself.
- *Dependencies still run one way.* `jobs` and `audit` are at the bottom, like `funnel`. An app that needs something done later calls `jobs.enqueue` with a kind and plain numbers; the handler lives in the app that knows how.
- *Erasure.* Erasing an account removes its candidates (they are about a person who is gone), empties `match_hint`, and leaves audit rows with the actor emptied or pointing at the stripped account. `erase_account` already keeps a shared person when another login is linked to it.

**Tests**

- The queue: three jobs run in order; a failing handler is retried with a longer wait each time and marked failed after five, with only the kind of error stored; a job queued inside a transaction that is undone does not exist; a job left running is queued again; two workers at once (threads) never run the same job twice; an unknown kind fails without stopping the others.
- The licence email: giving a licence queues one job and sends nothing until the worker runs; the email goes to the address the organization knows the member by and names no tier; an erased member gets nothing; a failed send is retried; joining with a licence sends none.
- The audit log: every organization-admin service writes a row with the right actor and no name or email in it; an undone action leaves no row; a Django admin action is copied; erasing the actor empties the link and keeps the row; only superusers can read it.
- Possible duplicates: the same phone flags a pair once, however often the rule runs; the same name flags only when both belong to an organization; a match-box address belonging to another account flags and the box is then emptied, and emptied too when it finds nothing; a rejected pair is not raised again; no rule changes any account's person.
- Linking: confirming shares personal licences between the two logins and each still sees only its own surveys; unlinking gives each its own back; a licence bought by B while linked returns to B; each step writes an audit row; Support staff cannot open the pages.
- Possible repeat: set when the person said yes, and when the same or a linked login has an earlier submitted survey; not set by an unreviewed pair; an organization's admin sees the mark and nothing about any other account.
- Tenant isolation: nothing about a possible duplicate, the match box or the audit log is on any organization page.

**PR plan** (one branch and one pull request each, in this order)

0. `m5-replan`: this section; T-23 (SES bounces) added to the backlog. Docs only.
1. `m5-jobs`: the queue, the worker command, the Jobs admin page with "Queue a test job", `/health/worker`, and the worker container.
2. `m5-licence-email`: the "you have been given a licence" email, sent by the worker.
3. `m5-audit`: the audit log, fed by the organization admins' services, the Django admin's history and erasure.
4. `m5-matching`: possible duplicates from phone and name, the superuser's review, linking and unlinking, `possible_repeat`.
5. `m5-match-box`: the optional box on the survey's start page, and its rule.
6. `m5-results-seam`: `Result`, a `compute_result` that returns nothing, its job.
7. `m5-docs-live-checks`: docs synced with what was built, and the founder's live checklist.

**Done when**

*The first four boxes are the founder's live checks.*

- [ ] The worker runs on the server: a test job queued from the Django admin shows as done within a few seconds.
- [ ] An admin gives a member a licence, and the member receives the email (at an address Amazon SES can deliver to while it is sandboxed).
- [ ] Two test accounts with the same phone number appear as a possible duplicate; a superuser confirms it and the second login can use the first one's unused personal licence; "Undo the link" puts them apart again.
- [ ] The audit log shows those actions and who did each, with no name or email in it.
- [x] All tests pass, including every tenant isolation test. *(1,786 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,786 tests, including every tenant isolation test. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Each code PR was checked by breaking the code on purpose and confirming a test fails: fifteen breaks in PR 1, ten in PR 2, thirty-nine in PR 3, sixty-four in PR 4, twenty-eight in PR 5 and sixteen in PR 6, 172 in all. 152 were caught at once. Eight showed real gaps in the tests, each of which got a test and is now caught: three in PR 3 (whether an action and its audit row are truly saved together), three in PR 4, and one each in PRs 2 and 6. The other twelve are not gaps: ten are places with a second check behind the first, one is a database rule that lives in a migration, and one was a break that changed nothing. Three tests run requests at the same moment in threads: two workers taking jobs (no job is done twice), two superusers deciding one pair (one wins, one is refused), and a survey started at the moment its login is linked.

Two runs in a real browser against a local server. On a desktop-width screen (PR 4), as a superuser: the list of possible duplicates, a pair with its two accounts side by side, "Same person" and its page that asks first, the link, "Undo the link", and the audit log showing each step by account number. At phone width (PR 5): the survey's start page, where the box appears only after "Yes", hides again with "No", is no wider than the phone, and the survey starts with it filled in.

On the live site, by machine only: each of the six deploys passed, including its "Worker check"; `/health` answered 200 and `/health/worker` answered "ok" after each; the worker's start-up line lists the jobs it knows (`compute_result`, `look_for_duplicates`, `send_licence_email`, `test_job`).

*Not covered by anything automated, and so not verified at all:* anything a person does on the live site. In particular the worker has never sent a real email: the licence email has been sent only to the tests' stand-in mailbox, and Amazon SES is still in its sandbox, where it refuses addresses it has not verified. If the email does not arrive in part B below, the job's row in the Django admin says what kind of error it was. No real pair of accounts has been through the look, and no real link has been made. The audit log and the possible-duplicates pages have been looked at in a browser only on a laptop.

**Live checklist (for the founder)**

Run this on the live site. You need window 1 (your superuser login, also for the Django admin), which is an admin of an organization with at least one licence left in its stock, and window 2 (a private window) with an ordinary account that is a member of that organization, has no licence there yet, and whose email address Amazon SES can deliver to (while SES is in its sandbox that means an address verified in SES). Part C needs a second ordinary account; one from an earlier checklist will do. Nothing here needs SSH, GitHub or the AWS console.

*Part A: the worker (box 1).*
1. Django admin, "Background jobs". The line above the list says "No job is waiting." or how many are and for how long.
2. Press "Queue a test job" at the top right. A row "test_job" appears. Wait five seconds and reload the page: its status is "Done".
3. In a new tab open `https://app.theaccelerare.com/health/worker`. It says "ok".

*Part B: the licence email (box 2).*
1. Window 1: your organization's Licences page. Beside the member from window 2, choose a tier and press "Give licence". The page answers at once, as before.
2. Within about ten seconds an email reaches that member: "You have a licence to take the survey for (your organization)". It names the organization and has a link. It does not name the tier.
3. Window 2: follow the link. It opens the start page of the survey for that organization (after logging in, if you were not).
4. Django admin, "Background jobs": a row "send_licence_email", "Done". Open it: it holds the number of the licence and no address.
5. If no email comes: open that row. A status of "Queued" with an error such as "SMTPRecipientsRefused" means Amazon SES refused the address (the sandbox, `06-backlog.md` T-4), not a fault in the site. It is tried again after 2, 4, 8 and 16 minutes and then marked "Failed"; select it and choose "Run the selected failed jobs again" once the address can receive mail.

*Part C: a possible duplicate, linked and undone (box 3).*
1. Pick two ordinary accounts that have different phone numbers; call the one that signed up first "older" and the other "newer". The newer one should have no personal licence. Django admin, "Entitlements", "Add": give the older account a Tier 1 licence, granted by hand. Log in as the newer one: "My surveys" says, under Personal, that taking the survey needs a licence.
2. As the newer account, open the profile and change the phone number to the older account's number.
3. Window 1: Django admin, "Possible duplicates". Within about ten seconds there is a row "Possible duplicate (n): accounts (a) and (b)", "Waiting for a decision", "They gave the same phone number." Open it. The two accounts are side by side: login, name, phone, organizations, surveys, unused licences.
4. Press "Same person…" at the top right. The page says what will happen. Press "Yes, link them". The message reads "Linked: account (b) now shares one set of personal licences with account (a)."
5. As the newer account, reload "My surveys". Personal now says "You have 1 unused licence", with a Start button. Do not start it.
6. Window 1: the same possible duplicate now offers "Undo the link…". Press it, read the page, press "Yes, undo the link".
7. As the newer account, reload "My surveys": it needs a licence again. The older account still has its one.

*Part D: the audit log (box 4).*
1. Django admin, "Audit log". The newest rows are what you have just done: "licence.given" from part B; "admin.added" for the licence you granted in part C; "accounts.linked" and "accounts.unlinked", each beside an "admin.changed" row that is the copy of the admin's own history line.
2. Every row says who as "Account #(number)", a link. Read down the page: there is no name and no email address anywhere on it. Follow one link: it opens that account.
3. Type the number of the possible duplicate into the search box: its rows are found.
4. If you have a Support staff login, log in to the Django admin with it: neither "Audit log" nor "Possible duplicates" is listed, and "Background jobs" is, to look at only.

*Part E, optional (no box): the box under "Yes".*
1. As an account with an unused licence, open the survey's start page. Choose "Yes": two things appear, "How did you take it?" and "An email address or phone number you used then (optional)". Choose "No": both go.
2. Choose "Yes", say how, type the email address of another of your accounts (one whose email is verified, and not one of the two from part C: a pair that has been decided is never raised again), and start the survey.
3. Django admin, "Possible duplicates": within about ten seconds that pair is there, and it says one of them typed an address or number that belongs to the other.
4. Django admin, "Responses", open that response: "Match hint" is empty. What was typed has already been deleted.

*Afterwards.* Tell Claude what you saw: the four boxes are then ticked in a docs-only PR. To close the pair from part C for good, press "Different people…" on a pair you do not want raised again; that cannot be reopened.

**Why this order / what to understand**

*Why a job queue at all.* Giving a licence should take a fraction of a second and never fail because a mail server is slow. If the email were sent inside the request, the admin would wait for it, or see an error for a licence that was in fact given. A queue separates "what you did worked" from "the follow-up happened". The follow-up can be tried again; the admin is already on the next page.

*Why the queue is a table, not a new service.* The usual answer is Redis and Celery: two more things to run, watch and pay for. A table in the database you already have, and one small loop that reads it, does the same job at this size and is something you can open in the Django admin and read.

*At-least-once and safe-to-repeat.* A worker can crash after doing a job and before writing "done". The job runs again. So every job must be safe to do twice. "Look for duplicates of account 7" is: the same pair cannot be stored twice. "Send an email" is not, which is why email is the one place a small risk is accepted.

*Why nothing links on its own.* A phone number changes hands; two people share a name. Linking two logins shares what one of them paid for with the other. That is a decision for a person who can look at both, and it has to be undoable.

*Why the audit log is in the same transaction.* A row saying "took back licence 12" written after the take-back was saved can be lost if the process dies in between, and then there is no record. In the same transaction, both happen or neither does.

---

## Milestone 6 — CSV downloads, the erasure record, the staff admin

*Re-planned on 2026-11-13. This section replaces the October outline, which predated much of the code: erasure and its admin page (Milestone 2), the audit log and the row erasure writes to it (Milestone 5), linked logins that share a person (Milestone 5), the results table (Milestone 5) and the Support staff group. What changed, and why, is under "What the re-plan corrects" and in the decision log.*

**Goal:** an organization's admins can download the list of surveys taken for it as a spreadsheet file; staff can download every submitted survey from the Django admin; each download is recorded; erasing an account records what was removed, as counts; there is a written procedure for deletion requests; and staff can find anything in the Django admin and see the numbers that matter on its first page.

**Status (2026-11-13).** Code-complete and deployed: PR 0 the re-plan (#100), PR 1 the organization's file (#101), PR 2 the two staff files (#102), PR 3 the erasure record (#103), PR 4 the numbers on the Django admin's first page (#104), PR 5 admin polish (#105), and PR 6, these docs. 1,988 tests. No migration was needed, so the database is as Milestone 5 left it. **Nobody has tried any of it by hand on the live site**, and no file has been opened in a spreadsheet program by a person: what remains is the founder's live checklist (below; `06-backlog.md`, T-27), which the first four "Done when" boxes wait for. What was built differently from the plan is marked *As built* where it applies and gathered under "As built" below; the builder's calls are under "Smaller rules" and wait for the founder's word. Merging on green without review ended with this milestone.

**How this milestone is run** (founder, 2026-11-13). As Milestone 5 was: each PR is merged once its check is green, without waiting for review, with a short summary after each. Product decisions are the founder's and are asked first; the four asked before this plan are the first four product rules below. Merging on green covers Milestone 6 only. **Nothing merges after 7:00pm PST on 2026-11-13**, and nothing risky after about 6:30pm: the founder shows the application at 8pm, and every merge that is not docs-only deploys to the live site. The PRs are therefore in order of what matters most. Whatever is not merged by the stop waits, and the founder is asked how to go on. *As it went:* all seven PRs were merged before the stop.

**What the re-plan corrects**

- *Erasure is already built.* The outline planned it here. It has existed since Milestone 2, has refused to strand an organization since Milestone 3, and has written an audit row and kept a shared person since Milestone 5. What is left is small: the audit row says *that* an account was erased but not *what* was removed, and nothing is written down about how a deletion request is handled.
- *The staff file names nobody.* The outline put `member_email` beside the 25 answers. The founder chose account numbers instead (below): a file saved on a laptop then holds no name, and stays that way after the person is erased.
- *Two staff files, not one.* The outline said "staff only". Staff are two groups: superusers, who can read answers, and Support staff, who cannot. Each gets a file that holds only what they can already see.
- *No `exports` app.* The outline and `03-tech-stack.md` planned `apps/exports/`. An export reads responses, and `responses` must stay the last app (its start-up step needs every other app's permissions to exist; `tests/test_app_dependencies.py`). So the export code lives in the responses app, beside the organization's responses pages, which are there for the same reason.
- *No results columns.* The outline said the organization's file "gains result columns once results exist". There is no algorithm, so there are no results. "Results level" in the file is the licence's tier, as on the page.
- *Already done, so not planned again:* a response is read-only in the Django admin; an account's contacts are listed on its page; a linked person survives the erasure of one of its two logins.
- *Left parked, on purpose:* what happens when a company asks for all its members' data to be deleted (`06-backlog.md`, D-2) and a "delete my account" button for people themselves (D-8). Both wait for the privacy lawyer.
- *The outline cited India's DPDP Act.* The site is built for the US first (2026-11-13). The written procedure is a draft for the privacy lawyer (D-7), not a statement of what any one law requires.

**The product rules**

- **An organization's file** (founder, 2026-11-13). One row for each *submitted* survey taken for the organization, with exactly what the responses page already shows its admins: name, email, the day it was started, the day it was submitted, results level, possible repeat. Never an answer, the "taken before" answer, or a survey someone took personally. Surveys still in progress are not in the file.
- **The staff file with answers** (founder, 2026-11-13). Every submitted survey on the site, with its 25 answers. Each person is an account number: no name and no email address. Superusers only.
- **The staff file without answers** (founder, 2026-11-13, over a superusers-only recommendation). Support staff may download a file that holds only what they can already see in the Django admin: the same rows, without the answers and without the "taken before" answer.
- **Every download is recorded** (founder, 2026-11-13) in the audit log: who, which organization or the whole site, and how many rows. No names.
- **Erasing an account records what was removed,** as counts and never as names: how many contacts, licences, memberships and unfinished surveys went, and how many submitted surveys were kept. The page that asks first shows the same counts before anything happens.
- **Staff see the numbers that matter** on the Django admin's first page: accounts, organizations, surveys submitted in the last seven days, possible duplicates waiting for a decision, and background jobs that failed or are waiting. Each number opens the list behind it. A member of staff sees only the numbers for pages they may open.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

*The organization's file*

- It is always every submitted survey for the organization. It does not follow the filters chosen on the page. Newest first, as the page lists them.
- An erased member is "Erased member" with no address, as on the page. Someone who has left the organization is still listed; the page's "(no longer a member)" note is not in the file, because the founder chose the six columns.
- A date is the day only, in UTC, written `2026-11-13`, so a spreadsheet sorts it (`06-backlog.md`, D-10).
- Results level is in the page's words: "Tier 2", and "Free (licence withdrawn)" when staff withdrew the licence. Possible repeat is "yes" or "no".
- The button is on the responses page and reads "Download as a spreadsheet (CSV)". It is a button, not a link: only a deliberate press makes a file and its audit row. With no submitted survey there is no button.

*The staff files*

- Both are on the "Responses" page of the Django admin, each behind a page that says what the file holds and that the download will be recorded.
- Columns: response number, account number, survey version, organization number and name (empty for a survey taken personally), tier (0 when the licence was withdrawn), the day started, the day submitted, possible repeat. The file with answers adds "taken before", how, and `q1` to `q25`.
- `q1` to `q25` are the statements by position, never their text. If a second survey version ever has more statements, the header is as wide as the longest version and the survey version column says which is which.
- The file without answers is for anyone who may open "Responses" in the Django admin (Support staff and superusers). It has no status column: every row is a submitted survey.
- A staff download is recorded straight into the audit log with the member of staff as the actor (`responses.exported`, with the number of rows and whether answers were in it). An organization admin's download is `responses.exported` too, with the organization as its target.

*All three files*

- A cell that begins with `=`, `+`, `-` or `@` gets an apostrophe in front, so a spreadsheet shows it as text and never runs it as a formula. A name is typed by the person, and an organization's name by its admin.
- The file starts with the mark that tells Excel it is UTF-8, so a name with an accent reads correctly.
- The file is made inside the web request and sent as it is read from the database, so a large one does not sit in memory. The row count in the audit log is taken as the download starts. This is right for tens of thousands of rows; a file that takes longer than 30 seconds to make would be cut off by the web server, and then belongs in the background worker. Milestone 7's load check measures it.

*Erasure*

- The counts come from the erasure itself, and from the three apps that already clean up their own copies when an account is erased (possible duplicates, the match box, an invite's address): each now reports how many it removed. *As built:* the page that asks first shows the erasure's own five counts; the audit row holds those and the three apps' counts, which are only known as the erasure happens.
- The page that asks first also says, when the account is one of two linked logins, that the other login keeps working and keeps its own licences.
- A result (once there is an algorithm) follows its survey: kept with a submitted survey, gone with an unfinished one. Nothing to build; a test holds it.

*The Django admin*

- The first page gets a panel above the list of pages. Nothing else about that page changes. *As built:* it also shows the surveys submitted in all, beside those of the last seven days; "the last seven days" runs from midnight seven days ago, the same as the "Past 7 days" choice of the admin's date filter, which the number links to; and a line that needs attention (a failed job, or jobs that have waited more than ten minutes) says so in red.
- In lists, an account, an organization or a survey shown in a column becomes a link to its own page. On the page of an account, an organization and a membership, a "Related" line links to its memberships, licences, surveys and payments. A link is shown only to someone who may open what it points at. *As built:* a link is not decided person by person (a column of a list is not told who is looking). Instead every page that is linked to is one Support staff may open, and a test follows every link as a superuser and as Support staff. A staff login given a hand-picked set of permissions could be shown a link that answers "forbidden", as it already could by the links Django itself puts on these pages. An organization's "Related" line has members, invites, join codes and payments; a membership's has licences and surveys; an account's has memberships, personal licences, surveys and payments.
- Search and filters are added where a page has none or too little (the list is under "What you build").
- Nothing in this milestone gives Support staff a permission they do not have, except the one download above.

*The written procedure* (a draft, for the privacy lawyer to confirm; `06-backlog.md`, D-7)

- Who may ask: the person, writing from an address that is verified on their account. A request from anyone else, an employer included, is not acted on (D-2).
- The request is answered within 30 days.
- What is removed and what is kept is what `erase_account` does today: the email, phone, name and login go; a submitted survey is kept with no link to a person; the audit log and the payment record are kept, and neither holds a name or an address.
- Erased data stays in the database's backups until they expire, 30 days later.

**What you build**

- `apps/responses/exports.py`: the rows of each file (plain values, built from the same facts the pages use), the guard against formulas, the streamed response, and the audit row. `organization_views.export` at `/organizations/<slug>/responses/export/` (POST; `scoping.for_admin`; the same `_taken_for` as the table, so the answers are not read from the database). `ResponseAdmin` gets two pages, `export/answers/` (superusers) and `export/` (anyone who may view responses), and its list page two buttons.
- `apps/accounts/erasure.py`: `Plan` gains the counts; `erase_account` writes them into the `account.erased` audit row; the receivers of `account_erasing` in `matching`, `responses` and `enterprises` return how many they removed. The erase page lists the counts.
- `templates/admin/index.html` and a template tag in the responses app for the counts (it is the one app that may import all the others).
- Admin polish, from an inventory of every admin page taken on 2026-11-13:
  - *Search:* Responses by the account's name, an account number and the organization's name (today: email only). Payments by the buyer's email, with the buyer as a column. Memberships by phone. Background jobs by kind.
  - *Filters:* Organizations by when they were made. People by whether they are linked. Invites and join codes by date. Responses by survey version and by personal or organization.
  - *Links in lists:* the account and the organization columns of Memberships, Invites, Join codes, Contact points, Entitlements, Responses, Payments, Possible duplicates and Results.
  - *"Related" links:* on an Account (memberships, licences, surveys, payments), an Organization (members, invites, join codes, payments) and a Membership (licences, surveys).
  - *Shown at last:* a licence's `granted_to` on its page.
- `docs/08-deletion-requests.md`: the procedure above, with the steps staff take in the Django admin.

**As built** (what differs from the plan above)

- *The files.* As planned. One addition: the organization's page and both staff pages are a button that sends a POST with the site's security token, so another website cannot make someone's browser download a file and write an audit row. The two staff addresses are `export/` and `export/answers/` under the admin's Responses page.
- *The erasure record.* The page that asks first shows the erasure's own five counts. The three counts from the other apps (possible duplicates, the box under "Yes", an invite's address) are only known as the erasure happens, so they are in the audit row only. The licences that are revoked now come from one function that both the count and the revoking use. Found and fixed on the way: for a linked login that is deleted outright, the summary sentence counted licences the other login in fact keeps.
- *The first page.* Also shows the surveys submitted in all. "The last seven days" runs from midnight seven days ago, as the admin's own "Past 7 days" filter does. A failed job, or jobs that have waited more than ten minutes, are marked in red.
- *Links.* Not decided person by person; every page linked to is one Support staff may open, and a test follows every link as a superuser and as Support staff. An organization's "Related" line has no "Surveys" (the admin refuses a filter two steps away); Responses can be searched by an organization's name instead.
- *Two admin pages* (erasing an account, loading the survey wording) had lost their dark breadcrumb bar under Django 6.1, and the erase page showed its heading twice. Both are fixed, and a test reads every admin template for the old markup.
- *The written procedure* is `08-deletion-requests.md`. It is a draft for the privacy lawyer and says so.

**Technical detail**

- *Streaming.* `StreamingHttpResponse` over a generator that reads the query with `.iterator()` and writes one line at a time with Python's `csv` module. Memory stays flat however many rows there are.
- *The organization's file cannot leak.* It is built from `_taken_for(enterprise)`, the query behind the table: it keeps to the one organization and leaves the answers out of the SQL. The isolation tests are written first and the new address joins the lists in `tests/test_tenant_isolation.py`.
- *The audit row first.* It is written before the first line is sent. If the download then fails halfway, the log says a download of N rows was started, which is the safe way round: there is never a file without a record.
- *One guard, used by all three files.* Every cell goes through one function; a test feeds it a name beginning with each of the four characters.
- *Tier* is the licence's tier at the moment of the download, 0 if withdrawn, as the pages show it.
- *Erasure counts are counted before anything is removed,* inside the same transaction and under the same locks, so the page's "what will happen" and the audit row's "what happened" are the same numbers unless something changed in between, in which case the audit row is the true one.
- *Links.* A list link is made by one helper (`apps/accounts/admin_links.py`). It does not ask who is looking; see "As built" under the Django admin's smaller rules. Support staff never see a link that answers "forbidden": a test follows every one.
- *The counts on the first page* are a handful of `COUNT` queries. Each is asked only if the member of staff may open that page.

**Tests**

- The organization's file: exactly the organization's submitted surveys, the six columns, an erased member with no name or address, a withdrawn licence; another organization's surveys, a personal survey and an unfinished one are absent; the answers are not read from the database; a member who is not an admin, an outsider and a logged-out visitor get the same answers as for the page; a GET makes no file; an audit row with the right actor, target and count, and no name in it.
- The staff files: a superuser gets the answers by position, in the right columns; no name and no email address anywhere in either file; Support staff get the file without answers and are refused the one with; an ordinary account is refused both; each download writes an audit row.
- The guard: a name starting with `=`, `+`, `-` or `@` is written with an apostrophe, in all three files.
- Erasure: the counts for an account that is deleted and for one whose survey is kept; the audit row holds them and no name; a linked login; a result is kept with its survey.
- The admin: each new search finds what it should; each link points at the right page and is absent for Support staff where they may not follow it; the first page shows the right numbers to a superuser and fewer to Support staff.
- Every code PR is checked by breaking the new code on purpose and confirming a test fails, and each new page is opened in a real browser (phone width for the organization's page, desktop width for the Django admin).

**PR plan** (one branch and one pull request each, in this order; most important first, because of the 7:00pm stop)

0. `m6-replan`: this section. Docs only.
1. `m6-export-organization`: the organization admins' file. Isolation tests first.
2. `m6-export-staff`: the two staff files in the Django admin.
3. `m6-erasure-summary`: what was removed, as counts, in the audit row and on the page.
4. `m6-dashboard`: the numbers on the Django admin's first page.
5. `m6-admin-polish`: search, filters and links across the Django admin.
6. `m6-docs-live-checks`: the deletion procedure, docs synced with what was built, the founder's live checklist and a backlog task for it, and the handoff file removed (the founder was asked first, and said yes).

**Done when**

*The first four boxes are the founder's live checks.*

- [ ] An organization's admin downloads the file on the live site and it opens cleanly in a spreadsheet.
- [ ] A superuser downloads the staff file with answers, and it names nobody; a Support staff login can download only the file without answers.
- [ ] A test account is erased from the Django admin and the audit log shows what was removed, as counts.
- [ ] The Django admin's first page shows the numbers, and each opens its list.
- [x] All tests pass, including every tenant isolation test. *(1,988 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 1,988 tests (1,836 before the milestone), including every tenant isolation test; the organization's download is in that file's lists, so an outsider, a member who is not an admin, a deactivated admin and a logged-out visitor are each tested against it. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Each code PR was checked by breaking the code on purpose and confirming a test fails: 31 breaks in PR 1, 39 in PR 2, 31 in PR 3, 25 in PR 4 and 45 in PR 5, 171 in all. 157 were caught at once. Eleven showed gaps in the tests, each of which got a test or tighter test data and is now caught: two in PR 2 (the order of the rows; the security token on the page's own form), two in PR 3, three in PR 4 and four in PR 5. The other three are not gaps: one is a place with a second check behind the first, and two were breaks that changed nothing, where the code they removed was itself removed.

Five runs in a real browser against a local server. At phone width (PR 1): the organization's responses page, the button under the list, the file it downloads, a name with an accent and a name written as a formula. At desktop width, as a superuser and as Support staff: both staff downloads, their pages and the "forbidden" answer (PR 2); the erase page, an erasure and its row in the audit log (PR 3); the first page, with every number followed to its list (PR 4); and a walk from a membership to its account, its surveys and its organization (PR 5). The browser found what the tests could not: a heading shown twice, two breadcrumb bars lost to Django 6.1, and labels squeezed onto two lines.

On the live site, by machine only: each of the five deploys passed, including its "Worker check"; `/health` answered 200 and `/health/worker` answered "ok" after each.

*Not covered by anything automated, and so not verified at all:* anything a person does on the live site. No file has been opened in Excel, Numbers or Google Sheets by a person; the tests read the files with Python's `csv` module. No large file was timed: a file that took more than 30 seconds to make would be cut off by the web server, and the new searches and the seven counts on the first page were not measured on a large database (Milestone 7's load check). The real survey wording was never used; the header of the staff file is built from positions, so the wording cannot reach it. The deletion procedure has been read by nobody but its author.

**Live checklist (for the founder)**

Run this on the live site. You need window 1 (your superuser login, also for the Django admin), which is an admin of an organization where at least one member has submitted a survey for it; and, for part C, a test account you are happy to lose. A Support staff login is useful for part B but not needed. Nothing here needs SSH, GitHub or the AWS console, and nothing here raises a Sentry alert ("forbidden" in part B is an ordinary answer, not an error).

*Part A: an organization's file (box 1).*
1. Window 1: your organization's Responses page. Under the list there is a button, "Download as a spreadsheet (CSV)". Press it. A file `responses-(your organization)-(today).csv` downloads and the page stays where it is.
2. Open the file in a spreadsheet program. The first row is `name, email, started, submitted, results_level, possible_repeat`. There is one row for each *submitted* survey; a survey still in progress is not there. No column holds an answer.
3. If any member's name has an accent, it reads correctly. Dates read as dates.
4. Django admin, "Audit log": the newest row is `responses.exported`, by your account number, with the number of rows and the organization's number, and no name.

*Part B: the staff files (box 2).*
1. Django admin, "Responses". At the top right: "Download as a spreadsheet…" and "Download with answers…".
2. Press "Download with answers…". The page says what the file holds. Press "Download the file". Open it: each row has an account number, `q1` to `q25`, and no name or email address anywhere.
3. Go back and press "Download as a spreadsheet…", then "Download the file". This file has no `q` columns and no `took_before`.
4. "Audit log": two new `responses.exported` rows, one with `answers: True` and one with `answers: False`.
5. If you have a Support staff login: log in to the Django admin with it and open "Responses". Only "Download as a spreadsheet…" is there. In the address bar, add `export/answers/` after `/admin/responses/response/`: the answer is a page that says "Not allowed" (since Milestone 7; before it, the browser's bare "403 Forbidden").

*Part C: the erasure record (box 3).*
1. Django admin, "Accounts": open the test account and press "Erase this account…". Under the sentence that says what will happen there is a table "In numbers".
2. Type its email and a reason, and press "Erase permanently".
3. "Audit log": type the account's number into the search box. The row `account.erased` holds the same numbers as the table, and three more (`possible_duplicates_removed`, `match_boxes_emptied`, `invite_addresses_removed`). No name and no email address.

*Part D: the first page (box 4).*
1. Django admin, the first page ("Home"). It starts with "At a glance": seven lines, each with a number.
2. Press each line in turn. The list that opens says the same number at the bottom ("5 accounts").
3. If "Background jobs that failed" is not 0, it is marked in red: open it to see what kind of error it was.

*Part E, optional (no box): finding things.*
1. Django admin, "Memberships". The account and the organization in each row are links. Press an account.
2. On the account's page, the "Related" line: press "Surveys (n)". The list holds that account's surveys only.
3. In "Responses", type a member's name into the search box, then an organization's name.

*Afterwards.* Tell Claude what you saw: the four boxes are then ticked in a docs-only PR. The deletion procedure, `08-deletion-requests.md`, is a page and a half: read it when you can, because its "who may ask" and "30 days" are the builder's draft, for you and the privacy lawyer.

**Why this order / what to understand**

*A download is the one place data leaves the site.* A page can be changed tomorrow; a file on somebody's laptop cannot. So the files hold as little as does the job (the organization's file holds what its admins already see; the staff file holds numbers, not names), and each download leaves a record of who took it.

*Streaming versus building the file.* Building the whole file in memory and then sending it works until the first big organization. A generator writes each row as it is read: memory stays flat and the download starts at once.

*Why a spreadsheet needs guarding.* A CSV file is plain text, but a spreadsheet treats a cell that begins with `=` as a formula and runs it. Someone could sign up with a name that is a formula, and it would run on the computer of whoever opens the file. An apostrophe in front makes it text again.

*The Django admin is your root console.* It is not pretty, and customers never see it. It saves building a dozen screens. Search, filters and links between related things are what make it usable at a thousand accounts.

*Erasure is scary on purpose.* It is the one action that cannot be undone, so it has a page that asks first, a reason, one transaction, and now a record of exactly what went. The duty is to delete when asked; the practical need is to be able to say what was deleted and when.

---

## Milestone 7 — Hardening and pilot launch

*Re-planned on 2026-11-13. This section replaces the October outline. What changed, and why, is under "What the re-plan corrects" and in the decision log.*

**Goal:** the site is safe to put in front of a first customer: a visitor who hits a wrong address or a fault sees a calm page in the site's design; a join code cannot be guessed by trying many; an error report says which account met it, by number; the site says in plain words what it stores and how to ask for deletion; the pages staff and admins use stay quick with a thousand surveys in the database; and there is a written checklist for the things only the founder can do (the AWS console, the first customer).

**Status (2026-11-13).** Code-complete and deployed: PR 0 the re-plan (#107), PR 1 the error pages (#108), PR 2 the privacy page (#109), PR 3 the limit on guessing join codes (#110), PR 4 the account number on Sentry's reports (#111), PR 5 the load check (#112), PR 6 "Send a test error" (#113), and PR 7, these docs. 2,054 tests. No migration was needed. **Nobody has tried any of it by hand on the live site**, no lawyer has read the privacy page, no error report has been looked at in Sentry, and none of the AWS console items has been done: what remains is the founder's (the live checklist below and `09-pilot-checklist.md`; `06-backlog.md`, T-28). What was built differently from the plan is marked *As built* or *New while building* where it applies. Merging on green without review ended with this milestone.

**How this milestone is run** (founder, 2026-11-13). As Milestone 6 was: each PR is merged once its check is green, without waiting for review, with a short summary after each. The founder was asked what to build before the 8pm showing and said "build it all"; and asked whether the privacy page should wait for a lawyer, and said to build it now from the facts. Merging on green covers Milestone 7 only. **Nothing merges after 7:00pm PST on 2026-11-13**, and no code after about 6:30pm: every merge that is not docs-only deploys to the live site the founder shows at 8pm. Whatever is not merged by then waits, and the founder is asked how to go on. *As it went:* all eight PRs were merged before the stop.

**What the re-plan corrects**

- *Already done, so not planned again.* The deploy has run Django's security check (`check --deploy`, failing on a warning) since Milestone 0, both on the image before it is shipped and on the server. Sentry already receives no personal data: no request bodies, no local variables, `send_default_pii=False` (Milestone 2). The uptime checker exists (2026-11-13, Better Stack). The erasure procedure already says how long erased data stays in backups (`08-deletion-requests.md`, Milestone 6).
- *What only the founder can do is not code.* The backup restore test (`06-backlog.md`, T-8), the CloudWatch alarms (T-7), MFA on the AWS login (T-6), the SSH port, the drill that stops the web container to see the alarm arrive, and looking at Sentry after a real error all need the AWS console or a deliberate fault on the live site. There is no AWS access on the build machine, and the project's rule is that those steps are the founder's. This milestone writes them down as one checklist (`09-pilot-checklist.md`); it does not do them.
- *The first pilot organization is the founder's too.* The outline's last box, "first pilot enterprise onboarded", needs a customer. The checklist says how to onboard one from the Django admin.
- *The SSH port stays as it is.* Decided on 2026-11-12 to revisit here. Closing it means the deploy pipeline needs another way to reach the server, which is a change to make on a quiet day, not the evening of a showing. It becomes a backlog task with the steps.
- *The privacy page is built now, without a lawyer* (the founder's choice, 2026-11-13, over a recommendation to wait). It states only what the site really does. It is on the privacy lawyer's list (D-7) to be read before the pilot.
- *Rate limiting is by account, not by IP address.* The outline said both. A join code is only ever checked for someone who is logged in, so every guess belongs to an account. The site sits behind Caddy, where a mistake in reading the visitor's address would count every visitor as one and lock them all out together. See "Smaller rules".

**The product rules**

- **A wrong address or a fault shows a calm page** in the site's design, with a way back. It never shows a traceback, and the "something went wrong" page works even when the database does not.
- **A join code cannot be guessed by trying many.** After ten codes that did not work within an hour, an account is asked to wait; a code that works is never refused because of earlier mistakes by someone else.
- **An error report says which account met the error, by number only.** Never an email address or a name.
- **The site has a privacy page** (founder, 2026-11-13), linked at the foot of every page: what is stored, who can see it, what an organization's admins see, what is kept when an account is erased, how long backups last, and how to ask for deletion.
- **The pages stay quick at a thousand surveys.** With 500 accounts and 1,000 surveys in a local database, an organization's responses page, its download, the staff downloads and the Django admin's lists answer in well under a second. An index is added only where a measurement shows it is needed.

**Smaller rules, the builder's calls** (raised here so they can be overruled)

- *Error pages.* "Not found" (404), "not allowed" (403), "your form has expired" (a failed security token) and "something went wrong" (500). They are plain pages with the site's heading and a link home, and no account menu: a "not found" page must look exactly the same for an organization that does not exist and for one the visitor may not see, byte for byte, which the tenant isolation tests hold it to. The 500 page is fixed text with its own few lines of styling, so it cannot fail for want of a file or a database.
- *The join-code limit.* Ten refused codes an hour per account. Every refusal counts (not valid, expired, switched off, used up), because each tells a guesser something. The count is kept in the site's cache table and forgets itself after an hour; staff cannot and need not reset it. The message says to wait an hour or ask the organization for a new code. An invite link is not limited: its secret is far too long to guess and it only works for the invited address.
- *Sentry.* The account's number is attached to an error report by a few lines of middleware. Nothing else about Sentry changes. The worker's jobs carry no person, so its reports stay as they are. *New while building:* a superuser can send a test error from the Django admin ("Background jobs", "Send a test error…"), which asks first. The job it queues fails once and then succeeds, so no failed job is left behind.
- *The privacy page* is at `/privacy/`, open to everyone, with no promises about the future: only what happens today. It names the companies that handle data for the site (Amazon Web Services for hosting and email, Stripe for payments, Sentry for error reports, Better Stack for the uptime check) and says the servers are in the United States. It says there are no advertising or tracking cookies, because there are none. How to ask for deletion: *as built,* the founder was asked which address to print and chose none for tonight, because the site's emails come from a noreply address nobody reads and the reply inbox is not chosen (`06-backlog.md`, T-14). The page says to ask the person at Accelerare who gave you access, or your organization's admin, and that a request is acted on once it comes from the address you log in with. The address is a setting, `CONTACT_EMAIL`: once it is set on the server the page prints it, with no code change.
- *The load check* is a command that only runs on a laptop (it refuses when `DEBUG` is off) and fills a separate local database, so the founder's own local data is not touched. Its numbers are written into this section. It is not part of the test suite.
- *An index, if one is needed,* is its own migration, added with a default name, and safe on a table with rows. *As built:* none was needed.

**What you build**

- `templates/404.html`, `403.html`, `403_csrf.html`, `500.html`, on a small shared layout (`templates/errors/base.html`) for the first three.
- `apps/enterprises/throttle.py` (the count) and the check in the `join_code` view; a message in `join_code.html`.
- `apps/accounts/middleware.py`: the account number for Sentry.
- `templates/privacy.html`, `config.views.privacy`, a foot on `base.html`.
- `apps/responses/management/commands/make_load_data.py`. *As built:* no migration; the measurements showed no index was needed.
- `docs/09-pilot-checklist.md`: the founder's console steps, the drill, and onboarding the first organization.

**Tests**

- Error pages: an unknown address, a refused page and a view that raises each give the right page and status; none holds a traceback, a setting or the visitor's email; the 500 page renders with the database unreachable; an organization's "not found" is still byte-for-byte the same as for one that does not exist.
- The limit: ten refusals are answered normally and the eleventh is asked to wait, without the code being looked at; a working code within the ten still joins; another account is not affected; after the hour it works again; nothing is counted for a logged-out visitor.
- Sentry: a logged-in request sets the account number and nothing else; a logged-out one clears it.
- The privacy page: open to a logged-out visitor, linked from every page's foot, and every factual sentence that can be checked by a test is (for example, that the only cookies set are the session and security-token ones).
- Every code PR is checked by breaking the new code on purpose, and each new page is opened in a real browser at phone width.

**PR plan** (one branch and one pull request each, in this order)

0. `m7-replan`: this section. Docs only.
1. `m7-error-pages`: the four error pages.
2. `m7-privacy-page`: the privacy page and the foot of every page.
3. `m7-join-code-limit`: ten refused codes an hour.
4. `m7-sentry-account`: the account number on error reports.
5. `m7-load-check`: the load command, the measurements, and an index if one is needed.
6. `m7-test-error`: *added while building.* "Send a test error…" on the Background jobs page of the Django admin, for superusers. The first "Done when" box asks the founder to see Sentry receive an error from the web site and from the worker, and there was no way to cause one without SSH. One press fails that request on purpose and queues a job that fails once in the worker and is done on its second try.
7. `m7-docs-live-checks`: the pilot checklist, the runbook and NOTES synced, the founder's live checklist and backlog tasks.

**Done when**

*The first five boxes are the founder's: they need the live site, the AWS console or a customer.*

- [ ] Error pages show on the live site (a wrong address; and, once, a deliberate fault), and Sentry receives an error from the web site and from the worker, with an account number and no name.
- [ ] The backup restore test is done and dated (T-8).
- [ ] The monitors fire when the web container is stopped (tested once, then restarted), and the CloudWatch alarms exist (T-7).
- [ ] The privacy page has been read by the founder, and by the privacy lawyer before the pilot (D-7).
- [ ] The first pilot organization is onboarded.
- [x] `check --deploy` is clean on every deploy. *(It has gated every deploy since Milestone 0, and passed on each of this milestone's six.)*
- [x] With 500 accounts and 1,000 surveys locally, the organization's page, the downloads and the admin's lists answer in under a second. *(Measured 2026-11-13: the slowest was 53 ms. See "The load check, as measured".)*
- [x] All tests pass, including every tenant isolation test. *(2,054 tests, in CI and locally, 2026-11-13.)*

**Checks at the end (2026-11-13)**

*Automated, all passing.* The full suite: 2,054 tests (1,988 before the milestone), including every tenant isolation test; the "not found" page is still the same, byte for byte, for an organization that does not exist and one that is not the visitor's. `ruff check`, `ruff format --check`, `manage.py check --fail-level WARNING` and `makemigrations --check`. Each code PR was checked by breaking the code on purpose: 13 breaks in PR 1, 12 in PR 2, 12 in PR 3, 8 in PR 4, 10 in PR 5 and 12 in PR 6, 67 in all. 62 were caught at once. Three showed gaps in the tests, each now closed (one in PR 3, two in PR 4). Two changed nothing, and in PR 4 the code that one of them removed was removed.

Four runs in a real browser against a local server: the three kinds of error page at phone width (PR 1); the privacy page and the foot of the login page at phone width (PR 2); eleven wrong codes typed into the join page at phone width (PR 3); and "Send a test error" at desktop width, from the link to the "Something went wrong" page to the job ending as "Done" (PR 6).

The load check, below, on a laptop.

On the live site, by machine only: each of the six deploys passed, including its "Worker check" and Django's security check; `/health` answered 200 and `/health/worker` answered "ok" after each; a wrong address answered 404 with the new "Page not found" page; and `/privacy/` answered 200.

*Not covered by anything automated, and so not verified at all:* anything a person does on the live site. No error report has been seen in Sentry, from the site or the worker: Sentry is not set up on a laptop or in CI. The "Something went wrong" page has only been shown by made-up faults in tests. The privacy page has not been read by a lawyer, and its statements about other companies come from this project's docs, not from a test. The join-code limit was not tried with two requests at the same moment. The load check measured one request at a time on a laptop, with at most 40 surveys in one organization. None of the AWS console items was done.

**Live checklist (for the founder)**

Run this on the live site with your superuser login. Parts A, C and D need nothing else. **Part B raises a Sentry alert on purpose** (an email, if Sentry is set to send one); nothing else is affected. The AWS console items, the uptime drill and bringing on the first organization are in `09-pilot-checklist.md`.

*Part A: the error pages (box 1, first half).*
1. Open `https://app.theaccelerare.com/no/such/page/`. The page says "Page not found" in the site's look, with "Go to the start page". Press it: you land on "My surveys".
2. If you have a Support staff login: log in to the Django admin with it and open `/admin/audit/auditlog/`. The page says "Not allowed".

*Part B: Sentry (box 1, second half).*
1. Django admin, "Background jobs", "Send a test error…" at the top right. Read the page, then press "Send the test error". You see "Something went wrong". That is the test working. Go back.
2. In Sentry, within a minute: two new errors named `DeliberateError`. The one from the web site shows a user id (your account's number) and no name or email address. The one from the worker reads "Job (number) (test_error) failed on try 1 of 5".
3. Back in "Background jobs": the row "test_error" says "Waiting". Two minutes later, reload: "Done", with 2 tries.

*Part C: the privacy page (box 4).*
1. At the foot of any page, press "Privacy". Read the page: it is one screen and a half.
2. Check each sentence against what you know. In particular "We do not sell your information", the four companies named, and "Deleting your account", which prints no address yet (`06-backlog.md`, T-14).

*Part D, optional (no box): the join-code limit.*
1. As an ordinary account, open "Join an organization with a code" and type a wrong code eleven times. Ten times it says the code is not valid; the eleventh asks you to wait an hour. That account cannot use any join code for the rest of the hour, so use a spare one.

*Afterwards.* Tell Claude what you saw: boxes 1 and 4 (the founder's half) are then ticked in a docs-only PR. Boxes 2, 3 and 5 are ticked as you work through `09-pilot-checklist.md`.

**The load check, as measured (2026-11-13)**

A scratch database on a laptop (`accelerare_load`), filled by `manage.py make_load_data` through the site's own services: 501 accounts, 10 organizations of 40 members, 1,000 submitted surveys (400 for organizations, 600 personal). Each page was loaded five times with Django's test client; the figure is the median, in thousandths of a second (ms). `DEBUG` was on, which makes Django slower, not faster.

| Page | ms | Database queries |
| --- | --- | --- |
| An organization's responses page (40 surveys) | 13 | 7 |
| The same, ordered by member | 11 | 7 |
| An organization's CSV download | 9 | 7 |
| An organization's members page | 10 | 6 |
| An organization's licences page | 12 | 10 |
| A member's "My surveys" | 8 | 11 |
| Django admin: the first page, with its numbers | 11 | 12 |
| Django admin: Accounts (and a search by email or phone) | 28 (10 to 11) | 5 |
| Django admin: one account's page | 24 | 13 |
| Django admin: Responses (and a search by name; by organization) | 33 (14; 41) | 5 |
| Django admin: Memberships (and a search by phone) | 31 (11) | 5 |
| Django admin: Entitlements (and a search by email) | 37 (17) | 6 to 8 |
| Django admin: one organization's page | 18 | 19 |
| Django admin: Audit log; Background jobs | 21; 34 | 8 |
| The staff CSV without answers, 1,000 rows | 40 | 5 |
| The staff CSV with answers, 1,000 rows | 53 | 7 |

Everything is far under a second, and no page asks the database more questions as the data grows (the lists show 100 rows a page). The background worker did the 2,780 jobs that making the data had queued (results, the look for duplicates, 390 licence emails to the laptop's console) in 20 seconds. **No index was added:** Django already indexes every link between tables, and nothing measured was slow. What this does not show: one organization with thousands of surveys (its responses page lists them all on one page), the live server (which is smaller than a laptop), or many people at once.

**Why this order / what to understand**

*Hardening last, not never.* Each earlier milestone already applied the standards from the opening section; this milestone checks them as a whole and adds the things that only make sense once the product is complete. It is not the milestone where security starts.

*Why the "something went wrong" page is so plain.* It is shown when something has already failed. If it needed the database, a stylesheet lookup or the logged-in account to draw itself, the failure that brought you there could break the page too, and the visitor would see nothing at all. So it is fixed text.

*Why a "not found" page says so little.* An organization the visitor may not see answers "not found", the same as one that does not exist, so nobody can learn which organizations exist by trying names. If the page showed the visitor's account menu, a clever comparison could still tell two answers apart. It shows the same bytes to everyone.

*The restore test is the backup.* A backup you have never restored is a hope. Doing it once, before any customer, turns it into a procedure you have run.

*Monitoring is three things.* Sentry tells you a request failed. The uptime check tells you the site is down (Sentry cannot, because nothing is running to report). CloudWatch tells you the disk is full before the site goes down.

*Why a load check.* "It is fast with my five test rows" says nothing. A missing index can turn a 10 millisecond query into 2 seconds at a thousand rows, and the responses page is the one customers watch.

---

## Phase 2 stub — the algorithm seam

Not a milestone, but worth doing in milestone 5 when the worker exists:

*(Built on 2026-11-13 as Milestone 5, PR 6. As built: `apps/results` imports no other app, so the `compute_result` job and the `recompute_results` command live in the responses app, which knows what a response is; the command takes no `--version` argument, because Django's own commands already use that name and the version is the one in `algorithm.py`; a response has one row per algorithm version, and working it out again with the same version replaces the row. **Needs SSH:** `recompute_results` is a command run on the server. When the algorithm arrives, give superusers a button for it in the Django admin.)*

- `apps/results/models.py`: `Result` (response FK, algorithm_version, payload JSON, computed_at). `apps/results/algorithm.py`: `ALGORITHM_VERSION = "0.0.0"` and `compute_result(response) -> dict | None` returning `None`. The `compute_result` job calls it and stores a row only if the return is not `None`.
- `apps/results/tiering.py`: `visible_fields(payload, tier) -> dict`, currently returning everything; the tier map is a dictionary from field name to minimum tier, filled in when the algorithm's output shape is known.
- A management command `recompute_results --version X` that enqueues `compute_result` for every submitted response, for re-runs.

When the algorithm arrives, Phase 2 is: implement `compute_result`, fill the tier map, build the results page that reads `Result` rows and calls `visible_fields`. Nothing in milestones 0–7 changes.

---

## Phase 3 stub — payments

*Moved on 2026-11-13: payments are now Milestone 4b, straight after Milestone 4, and "likely Razorpay for India" below is deferred with the rest of the India plans (the site is built for the US first). The paragraph is kept for what was already decided.*

Not a milestone. Self-serve purchase for individuals and enterprises (likely Razorpay for India) writes licences through the same services the admin uses: `grant_individual` with source `purchase`, and the seat-pool services. Already decided: licences do not expire, a retake needs another licence, upgrades happen in place. Needed when payments arrive: a payment ledger (amount, currency, date, invoice number, provider reference, the licence id and tier) that carries no personal identity, so erasing a person never removes an accounting record; refunds revoke the licence through the service; the funnel records `licence_granted` with source `purchase`; and a reminder path for unused licences once the worker exists. Nothing in milestones 0–7 changes.

---

## Milestone map

| # | Milestone | Depends on | Deployable result |
| --- | --- | --- | --- |
| 0 | Foundations and first deploy | — | Empty site on HTTPS with CI/CD |
| 1 | Accounts | 0 | Sign up, verify, log in, reset |
| 2 | Survey and responses | 1 | Individuals take and view the survey; licences, erasure and the funnel are built (closed 2026-11-12) |
| 3 | Organizations, memberships, join | 2 | Organization admins onboard members and see who took the survey; licences per membership (built 2026-11-13; the founder's live checks remain) |
| 4 | Licences for organizations (seat pools) | 3 | An organization's admins give out the licences it has bought; counts are right (built 2026-11-13; the founder's live checks remain) |
| 4, part 2 | Licences set aside for invites and codes | 4 | A licence promised by an invite or a code is really there; an invite can be sent again or moved (built 2026-11-13; the founder's live checks remain) |
| 4b | Payments | 4 | A purchase adds licences without staff typing (built 2026-11-13; Stripe's test keys reached the server the same day; the founder's live checks remain) |
| 5 | Jobs, possible duplicates, audit | 4b | Worker live; a member is emailed their licence; possible duplicates reviewed and linked by a superuser; actions audited (built 2026-11-13; the founder's live checks remain) |
| 6 | CSV downloads, the erasure record, the staff admin | 5 | An organization's admins and staff download surveys as CSV, each download recorded; an erasure records what it removed; a written deletion procedure; search, links and counts in the Django admin (built 2026-11-13; the founder's live checks remain) |
| 7 | Hardening and pilot | 6 | Error pages, a privacy page, a limit on guessing join codes, account numbers on error reports, a load check; the pilot checklist for what only the founder can do (built 2026-11-13; the founder's live checks, the AWS console items and the first customer remain) |

## When to stop and ask

Ask for help (here, or anyone experienced) rather than pushing on when:

- Milestone 0's deploy has eaten more than a couple of days. It's almost always one networking or TLS detail and a second pair of eyes finds it fast.
- A tenant-isolation test is hard to make pass. That's the one place where "I'll fix it later" is not acceptable.
- You're about to write raw SQL, a custom migration operation, or anything with the word "clever" in your head.
- Something works locally and not on the server. The difference is always in configuration; compare `.env` to `.env.example` first.

## Open follow-ups

Moved on 2026-11-12 to `06-backlog.md`, the one list of open tasks and parked decisions: the remaining live checks (Milestone 1 parts E, F and the uptime checker G), the wait on SES production access, and every open decision that used to be listed here. Add new follow-ups there, not here.

## Decision log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-11-13 | Milestone 7 is code-complete and deployed: PRs 0 to 7 (#107 to #113 and the closing docs PR), all merged before the 7:00pm stop. What remains is the founder's: the live checklist (`06-backlog.md`, T-28), the AWS console items, and the first pilot organization (`09-pilot-checklist.md`). Decisions and calls made on the way: the privacy page prints no address for now (the founder's choice; the reply inbox is not chosen, T-14) and takes one from a setting, `CONTACT_EMAIL`; the join-code limit is ten refusals an hour, by account and not by IP address; the error pages carry no account menu, so "not found" stays the same bytes for everyone; no index was added, because nothing measured needed one; and one PR was added, "Send a test error" in the Django admin, so that Sentry can be checked without SSH. The SSH port stays as it is and is now a backlog task (T-29). Merging on green without review ended with the milestone | The plan left these to the builder, except the address, which the founder was asked about |
| 2026-11-13 | Milestone 7 re-planned into seven PRs (0 to 6): error pages, the privacy page, a limit on guessing join codes (by account, not by IP address), the account number on Sentry reports, a load check with indexes if measured, and a checklist for what only the founder can do (the AWS console items, the drill, the first pilot organization). The SSH port stays open with key-only login for now and becomes a backlog task | The October outline listed console work and a customer beside the code, and planned checks that already run on every deploy |
| 2026-11-13 | The founder's answers for Milestone 7: it is run like Milestone 6 (merged on green, Milestone 7 only); all of it is built before the showing ("build it all"), over a recommendation to build the safest parts first; and the privacy page is built now from the facts, without waiting for the privacy lawyer, over a recommendation to wait | Asked together before the plan, with `AskUserQuestion` |
| 2026-11-13 | Milestone 6 is code-complete and deployed: PRs 0 to 6 (#100 to #105 and the closing docs PR), all merged before the 7:00pm stop. Its four live checks wait for the founder (`06-backlog.md`, T-27). Builder's calls made on the way, all listed in its "Smaller rules" and "As built": a download is a button that sends a POST, never a link; the file does not follow the page's filters; the erase page shows five counts and the audit row eight; "the last seven days" is the admin's own "Past 7 days"; links in the admin are not decided person by person, but every one leads somewhere Support staff may go; the deletion procedure (`08-deletion-requests.md`) is a draft for the privacy lawyer. Merging on green without review ended with the milestone | Each keeps a promise the plan made (a download is always recorded; the number and the list agree; Support staff never meet "forbidden") in the simplest way the Django admin allows |
| 2026-11-13 | Milestone 6 re-planned into seven PRs (0 to 6), most important first because nothing merges after 7:00pm that day: the organization's file, the staff files, the erasure record, the numbers on the Django admin's first page, admin polish, closing docs. The export code lives in the responses app, not a new `exports` app. The builder's calls are under "Smaller rules" in the Milestone 6 section, among them a draft deletion procedure (requests from the person only, answered within 30 days) for the privacy lawyer | The October outline planned erasure that already exists, put an email address beside the answers, and planned an app that cannot sit after `responses` in the dependency order |
| 2026-11-13 | The founder's four answers for Milestone 6. An organization's CSV file has the columns its responses page shows (name, email, started, submitted, results level, possible repeat), for submitted surveys only. The staff file has the 25 answers and names nobody: people are account numbers. Support staff may download a file without answers (the recommendation was superusers only). Every download is written to the audit log | Asked together before the plan, with `AskUserQuestion`; three were "as recommended" |
| 2026-11-13 | Milestone 5 re-planned into eight PRs (0 to 7). Nothing links two accounts automatically: possible duplicates go to a superuser, who links, rejects or unlinks. The "Done when" box about a shared verified email is replaced, because the decision of 2026-10-09 already ruled that out. The invite email stays in the request; the worker's first email is "you have been given a licence". Staff actions reach the audit log by copying the Django admin's history lines; organization admins' actions are recorded by the services. The results seam of the Phase 2 stub is built here | The October plan contradicted itself on verified email, relied on phone verification that does not exist, and predated the invite page's "sent or copy the link" answer and its count of emails |
| 2026-11-13 | Milestone 5 built (PRs 1 to 7, #85 to #91). Builder's calls made on the way, all listed in its "Smaller rules" for the founder: two linked logins at most per person; undoing a link returns each licence by who used it and who it was granted to (`Entitlement.granted_to`); a link that was undone can be made again; the match box is always emptied after use; the audit log names people by account number only and never copies an admin history line's label; the look for duplicates also runs on a change of phone or name and on joining an organization | Each keeps a promise the plan made (undo is exact; no name or email in the log; what a person typed is kept as briefly as possible) in a simpler way than the plan's own wording allowed |
| 2026-11-13 | The founder's setup day, as they reported it: the uptime checker is set up on Better Stack's free plan (T-2 closed; four small follow-ups are T-26); Sentry is on its free plan with no payment method; Stripe's test keys and webhook secret are in Parameter Store and reached the server the same afternoon, and receipts are switched on in the sandbox (T-21 closed; T-22 can be run); SES production access turned out to have been refused on 2026-10-10 and was asked for again (T-4). Stripe's "Managed Payments" was skipped at sign-up and joins D-20. The reply inbox (T-14) was left undecided | Claude could not see any of the consoles; only the arrival of the webhook secret on the server was checked from outside |
| 2026-11-13 | The interface points the founder raised on the live site in October (backlog T-19) are built, each as its own PR (#93 to #97): the last page's button reads "Submit" and finishes the survey, with the old "ready to submit" page kept only as the way back if that did not finish; "you need a licence" is said once; a "Show password" button under every password box; the account's page in the Django admin says only whether a password is set; two actions make or unmake Support staff, asking first. The founder chose, for the profile: a tidy "Your account" page whose forms open only when asked for, and "My surveys" as the page a login lands on (an account with no verified email or no name still lands on the account page). T-25 is built too: a superuser can look for possible duplicates of selected accounts. Found on the way and fixed: for a phone number outside the US the profile's hidden country field stayed on "US", so the number retyped without its code was refused | The founder asked for all of T-19 and T-25 on 2026-11-13. One suggestion that sat in T-19 and was the builder's, not the founder's, was not built: wording "Give another licence" for a member whose last one is used |
| 2026-11-13 | Milestone 6 is next, planned and built like Milestone 5: merged on green without review, decisions raised to the founder as they come up | The founder's instruction of 2026-11-13 |
| 2026-11-13 | A member is emailed when an admin gives them a licence; only superusers review possible duplicates; recording SES bounces and complaints becomes a backlog task (T-23). Replaces the 2026-11-12 row "Milestone 5 records SES bounces and complaints" for now | Founder's defaults, put to them before the re-plan and accepted ("those defaults are fine"). The SES part needs the AWS console |
| 2026-11-13 | Milestone 4b is code-complete and deployed: PRs 0 to 5 (#78 to #82 and the closing docs PR). Buying stays closed on the live site until the founder adds the Stripe test key (`06-backlog.md`, T-21), and its three live checks then wait for the founder (T-22). Nothing has been run against Stripe itself | The site was built to work with or without the keys, so the code did not have to wait for the Stripe account |
| 2026-11-13 | Milestone 4b (payments) is planned in six PRs (0 to 5): Stripe's hosted payment page; prices in the database; a ledger row written before the money moves and holding no identity; the licence given exactly once, from the return page or Stripe's message, whichever comes first; refunds from the Django admin. The defaults the founder accepted beforehand are the product rules; the builder's further calls are under "Smaller rules" | The founder answered the basics and accepted the defaults ("those defaults are fine") before going away, and asked for it to be planned and built without waiting |
| 2026-11-13 | The buy pages are open to everyone on the live site while Stripe is on test keys | Founder: "treat it like it's live with customers"; nobody is looking at the site yet, and on test keys no money can move |
| 2026-11-13 | The licence changes (Milestone 4, second part) are code-complete and deployed: PRs 0 to 2 (#75, #76 and the PR that wrote this line). Its two live checks wait for the founder (`06-backlog.md`, T-18). One rule changed while building: an invite's 14 days restart only when its email actually goes out, not on a send the mail server refused | A refused send reaches nobody, so it should neither count towards the five nor keep an invite, and the licence set aside for it, alive |
| 2026-11-13 | The licence changes are planned as "Milestone 4, second part": three PRs (0 to 2), built before payments. Its builder's calls are listed there under "Smaller rules": what emailing again and moving do to the link and the 14 days, that a move uses no extra place, that only accepted emails count towards the five, and that a join and its licence now happen together or not at all | They change how the stock is counted, which a purchase adds to. The founder asked for small choices to be made sensibly and listed rather than asked one at a time |
| 2026-11-13 | The founder's answers to the seven choices made while building Milestone 4 (was `06-backlog.md`, D-18). Kept as built: a member holds one licence in hand at a time, whoever it came from; what the Licences page lists and offers; a member who comes back with an invite keeps an unused licence and gets no second one. Overruled: the page read before joining must say when the invite or code comes with a licence; and a tier may no longer be put on an invite or a code while the stock has none (next row). The wording of the sentence on that page was left to the builder, and the "joined without a licence" warning goes away with the new design | The founder took them one at a time. The full text of each is under "Smaller rules" in the Milestone 4 section |
| 2026-11-13 | A licence is set aside out of the organization's stock when an invite or a join code with a tier is made, and making one is refused when none of that tier is left. An unused invite can be emailed again or moved to another address: the old link stops working and the licence follows the new address. An invite is emailed at most five times in all. Withdrawing an invite or letting it expire returns its licence to the stock. A join code sets aside one licence for each person it allows; the unused ones return when it is switched off or expires. Replaces "the stock is checked when the person joins" and the rule of the same day that someone may join without the promised licence | Founder's design: a person who is promised a licence gets it, and an admin cannot promise more than the organization has bought. The invite parts are the founder's; the join code part and the cap of five were left to the builder and accepted |
| 2026-11-13 | The GitHub repository stays public (was `06-backlog.md`, D-19) | Founder's decision. No secret is in it and the survey statements were never committed |
| 2026-11-13 | `main` is protected on GitHub (was `06-backlog.md`, T-20): a change reaches it only through a pull request whose `test` check has passed, with no bypass for administrators, no force push and no deleting the branch. No approving review is required, and a branch does not have to be up to date with `main` before merging. Set by Claude through the GitHub API at the founder's word | Until now every merge waited for green checks by habit only. A second reviewer does not exist, so requiring an approval would block every merge |
| 2026-11-13 | The payments basics (was the list under `06-backlog.md`, T-17): Stripe for now, on test keys until the founder has tried a purchase; $1, $2 and $3 for Tiers 1 to 3 as placeholder prices, changeable without code; no volume price; an upgrade charges the difference; a refund only for an unused licence within 30 days, by staff from the Django admin, and for an organization only licences still in its stock; no sales tax collected at first, with Stripe's tax setting able to be switched on without a code change; Stripe's receipt for a person and a numbered invoice as well for an organization | Founder's answers, mostly "as recommended". Tax and invoices are marked for review with an accountant before real prices are set (`06-backlog.md`, D-20) |
| 2026-11-13 | Merging on green without waiting for review applies again, to the pull request recording these decisions, the licence changes, payments (Milestone 4b) and Milestone 5. Product choices that come up are still the founder's and are asked before building, not guessed | The founder was asked when payments came up, as the arrangement required, and said yes; later the same day they asked for Milestones 4b and 5 to be planned and built the same way while they were away |
| 2026-11-13 | Milestone 4 is code-complete and deployed: PRs 0 to 5 (#67 to #71 and the closing docs PR). Its four live checks wait for the founder (`06-backlog.md`, T-18). Merging on green without review ended with the milestone; whether it applies to payments is asked when that milestone is planned (T-17) | The arrangement was given for Milestone 4 only |
| 2026-11-13 | Builder's calls in Milestone 4, each recorded in its PR and listed under "Smaller rules" in the Milestone 4 section: one licence in hand at a time whoever it came from; what the Licences page lists and offers; the page before joining says nothing about a licence, and its last sentence was reworded; a returning member gets no second licence; a tier can be chosen while the stock is empty; when the "joined without a licence" warning stops counting someone; who is recorded as the giver of a licence given on joining. They wait for the founder's word (`06-backlog.md`, D-18) | Raised to be overruled, not decided |
| 2026-11-13 | Test helpers build their data through the widest real service call, never one row at a time and never past the services. A push to `main` that changes only documents is not deployed. The deploy keeps running the tests on `main`. CI lists its ten slowest tests on every run (#72) | The founder asked for the pipeline to be made quicker without making the project less safe. 42% of the suite's work was one helper answering surveys a statement at a time; a docs-only merge rebuilt an identical image; and `main` has no branch protection, so the run on `main` is the only gate before the server (`06-backlog.md`, T-20) |
| 2026-11-13 | Milestone 4 re-planned into six PRs (0 to 5) and run as Milestone 3 was: merged on green without waiting for review, decisions raised, a summary after each PR. The arrangement covers Milestone 4 only | Founder's instruction; it worked for Milestone 3 |
| 2026-11-13 | A licence from an organization's stock counts against the tier it has now from the moment it is given. The admin can take it back until the survey is submitted (an unfinished attempt is deleted after a warning); a submitted one is spent for good. Its tier can move up or down before submission and only up afterwards | Founder's decisions for Milestone 4, taken one by one: a mistake can be undone, a used licence cannot be reused |
| 2026-11-13 | A deactivated member's unused licence stays with the membership (as decided for Milestone 3), and the admin can take it back to the stock | The organization should not lose a licence it paid for because someone left |
| 2026-11-13 | Someone joining with an invite or a code that carries a tier, when none of that tier is left, still joins, without a licence; the admin is warned | The person holding the invite did nothing wrong |
| 2026-11-13 | The people limit is the base number (25, still changeable by staff) plus every licence the organization has bought, across all tiers. Settles `06-backlog.md` D-16 | Simple to explain, leaves room for people who join without a licence, and still caps how many invite emails go out |
| 2026-11-13 | Licences staff grant by hand are outside an organization's stock; only licences given from the stock count against it | Staff can help a customer without changing what was sold, and the stock stays an honest record of sales |
| 2026-11-13 | Superusers and Support staff can both set an organization's stock in the Django admin, until payments set it automatically | Founder's choice "for now", over a superusers-only recommendation, because payments follow straight after |
| 2026-11-13 | Invites and join codes can carry a tier in Milestone 4, built as its last feature PR | An admin inviting thirty people should not have to give thirty licences one by one |
| 2026-11-13 | The site is built for the US first; expanding to India is a later conversation. Everything India-specific in these docs (Razorpay, GST, SMS sender registration, the DPDP Act, the move to Mumbai) is deferred, not dropped | Founder's decision |
| 2026-11-13 | Payments move from Phase 3 to a milestone of their own straight after Milestone 4 (Milestone 4b), to be planned with the founder before any code | The founder asked why staff type an organization's stock by hand; it is only because the site cannot take payments |
| 2026-11-13 | Milestone 3 is code-complete and deployed: PRs 0 to 13, plus #62 to #64. Its six live checks wait for the founder (`06-backlog.md`, T-16). Merging on green without review ended with the milestone; whether it applies to Milestone 4 is asked when that milestone is re-planned | The arrangement was given for Milestone 3 only |
| 2026-11-13 | In the staff admin every action on an organization (deactivate, reactivate, make admin, make member, withdraw an invite, switch off a code) shows a confirmation page first and writes a history line with no email or name in it. Support staff can look at the four pages and hold one extra permission, `deactivate_membership`. A join code is shown only to superusers; an invite's link secret to nobody | Two of the actions cannot be undone and a wrong pick in a dropdown is easy; its own permission makes "deactivate only" exact; a code and a link are ways in |
| 2026-11-13 | The wording that tells a member what an organization's admins can see (the join confirmation and the organization "Before you begin" page) stays as built for now and is reviewed with the privacy lawyer's list (`06-backlog.md`, D-17) | The founder read both and said "fine for now" |
| 2026-11-12 | An account can create at most three organizations itself; staff can create more for it in the Django admin | Founder's decision during the build: each organization can send its own 25 invites, so without a cap the people limit means little |
| 2026-11-12 | Erasing an account that is the only active admin of an organization with other active members is refused until another member is made admin. With nobody else active it goes ahead and the organization is left empty | Founder's decision during the build: an organization people still use must not lose its only admin as a side effect |
| 2026-11-12 | Deactivating an admin also makes them an ordinary member; someone who comes back stays a member until promoted again | Founder's decision during the build: being an admin again should be done on purpose |
| 2026-11-12 | The email an organization's admins see for a member is the address the invite was sent to if they joined by invite, otherwise the address they log in with; the join confirmation page says which | Founder's decision during the build: it is the address the organization already knows the person by |
| 2026-11-12 | Builder's calls in Milestone 3, each recorded in its PR: the responses page is a list with a plain filter form (no HTMX, no wide table); those pages live in the responses app; joining is check, confirm, then join, and reveals nothing while logged out; organization pages give templates plain values only; membership foreign keys are `PROTECT`; an invite email names the organization, not the admin; refusals say why in plain words; `new` is a reserved slug and a name with no usable letters gets the slug `organization` | The plan left these to the builder; listed so nobody has to rediscover them |
| 2026-11-12 | Milestone 3 re-planned into fourteen PRs (0 to 13); PRs are merged on green without waiting for the founder's review, decisions are still raised, each PR ends with a summary, and the milestone ends with automated checks and a founder checklist | Founder's instruction, to move quickly towards the walkthrough on 2026-11-13 without giving up the decisions |
| 2026-11-12 | A licence belongs to a person or to a membership, never both, and decides the context of the response that uses it; staff grant membership licences by hand until seats exist. The model half of Milestone 4 moves into Milestone 3 | One fact instead of two that could disagree; Milestone 4 needed the same schema change |
| 2026-11-12 | The site says "organization" (US spelling, the founder's choice); code, tables and docs keep "enterprise" | Covers companies and schools; renaming the code buys nothing |
| 2026-11-12 | Sign-up asks for a full name (`Account.full_name`); earlier accounts are asked on the profile; erasure removes it | Organization admins would otherwise see members by email only, and Milestone 5's name rule needs it |
| 2026-11-12 | Organization admins can promote a member to admin and demote an admin; the last active admin is protected | Otherwise every change of admin is a support request |
| 2026-11-12 | An organization that has not bought licences can bring in 25 people in total, by invite or code; every invite ever sent counts; staff raise `people_limit` by hand | Founder: anyone may create an organization, but it is very limited until it pays; also stops the invite form being used to send spam through SES |
| 2026-11-12 | A deactivated member cannot rejoin with a shared code; an admin reactivates them or sends a fresh invite. Overrides the original "redeeming reactivates" | Deactivating someone should keep them out |
| 2026-11-12 | Smaller Milestone 3 calls agreed by the founder: admins are members too; members never see other members; admins never see phone numbers, personal responses or how far a draft has got; deactivating deletes the organization draft and keeps the licence with the membership; invites are single use, last 14 days, need the verified invited address, and the link can be copied if the mail fails; codes are `XXXXX-XXXXX` with a 30-day default; tier on a code or invite is stored but hidden until Milestone 4; a join shows what admins will see first; an unknown slug and someone else's slug are both 404; erased members show as "Erased member" and their address leaves their invites | Listed to the founder on 2026-11-12 and accepted as a set |
| 2026-11-12 | Milestone 2 is closed. Milestone 3 starts when the founder says so | Every "Done when" box is ticked; the open Milestone 1 checks do not block it |
| 2026-11-12 | Enterprise admins see a member's response status, dates and tier (and results from Milestone 5), never the answers or the self-report; the enterprise CSV export has no answer columns | Consistent with members never seeing their own answers; safest for the privacy review; easy to widen later. Settles FR-19's enterprise scope |
| 2026-11-12 | Erasing a person keeps their membership link; the stripped response stays visible to the enterprise and counts in its historical total | Founder's choice, for the privacy lawyer to confirm; enterprise-wide deletion requests are still open |
| 2026-11-12 | Replies to site emails go to a monitored inbox through a Reply-To header; the address is still to be chosen | People reply to verification and reset emails when they are stuck |
| 2026-11-12 | Milestone 5 records SES bounces and complaints and stops sending to those addresses | AWS can pause sending if the rates get too high |
| 2026-11-12 | SSH exposure is revisited in Milestone 7 | Key-only SSH is an acceptable risk for the trial |
| 2026-11-12 | Milestone 2's live checks (tasklist parts A to D: real wording loaded and none of it in git history; survey taken and resumed on a phone; second attempt needs a second licence; revoke shows "Free (licence withdrawn)"; superuser and Support staff views of the admin; the funnel; erasing both ways and signing up again) are done, and every Milestone 2 "Done when" box is ticked | Founder ran them on the live site; the Milestone 1 browser checks (E, F) and the uptime checker (G) stay open |
| 2026-11-12 | Tier names stay "Tier 1/2/3" and "Free" for now | Founder's call; renaming is one template |
| 2026-11-13 | `/` sends a logged-in person to their profile and anyone else to the login page (was backlog T-15) | Nothing answered at `/`, so the header link and logging out both showed "Not Found". A real landing page is a later question |
| 2026-11-13 | The tests run in parallel with a fast password hasher (`config/settings/test.py`, `pytest-xdist`) | The suite took about 100 seconds and ran three times per PR; it now takes about 17 locally and 25 in CI. The site keeps Argon2 |
| 2026-10-18 | allauth's "Email addresses" admin page (now under "Login (allauth)") is read-only; only its "mark verified" action stays | Each email lives in our table and allauth's, and only the services keep them in step; the action fires allauth's signal so our contact point is verified too, and while SES is sandboxed it is the only way to verify an address that cannot get mail |
| 2026-10-10 | Milestone 2 ends with PR 11: the founder's live checks as one tasklist, then a docs-only PR that ticks the boxes | All the code is done; what remains needs the live site and a real phone |
| 2026-10-10 | Caddy refuses request bodies over 5 MB, and `deploy.sh` reloads Caddy on every deploy | Without a limit Django streams a large upload to disk before any view can check it; the deploy never restarted Caddy, so a Caddyfile change would not have applied |
| 2026-10-10 | The licence grant form searches for the account (the admin's autocomplete) instead of a dropdown of every account | Works as accounts grow; searches by email or phone like the Accounts page |
| 2026-10-10 | Sentry receives no request bodies and no local variables, site-wide | sentry-sdk sends both even with `send_default_pii=False`, and they can hold answers, emails or the statements |
| 2026-10-10 | Support staff keep read access to the questions for now | Founder's call; revisit when the group is split |
| 2026-10-10 | The survey wording is loaded by a superuser on the survey version's admin page: Check shows counts only; Apply goes through `load_questions` under a lock and is refused if the wording changed since the preview; a submitted survey on the version needs an "I understand" tick; limits 200 KB a file and 1,000 characters a statement | No SSH; the wording never appears on the page, in messages, history or logs; two superusers cannot overwrite each other; people mid-survey keep their answers and see the new wording from their next page |
| 2026-10-10 | Revoking a licence deletes an unfinished attempt on it; a submitted survey is kept but shows "Free (licence withdrawn)" with no results | The draft could never continue and would block a new start (one open draft per account); founder chose refund-like behaviour for the submitted case |
| 2026-10-10 | Page 1 cannot lock until the self-report is answered; the draft is created by the start page's POST, never a GET | Opening the page must not cost a licence; the self-report is fixed once the statements begin |
| 2026-10-10 | Survey funnel events (`survey_started`, `page_locked`, `survey_submitted`) carry tier and source | Conversion by tier and by purchase or manual grant, still with no link to the account |
| 2026-10-10 | Survey URLs: `/survey/start/`, `/survey/history/`, and `/survey/<id>/...` for one attempt | The id stays in the address because Milestone 3 allows a personal and an enterprise draft at once |
| 2026-10-10 | Answers are accepted only for the page being answered; Next saves the ticks the page shows together with the lock, and an incomplete page keeps them; the page is one form | Nobody answers a statement they have not seen; Next works without JavaScript, rescues a failed autosave, and with two tabs the locked page is the one on screen |
| 2026-10-10 | "Already locked" or "already submitted" is treated as done (redirect, or the whole window moves for an autosave), never an error | A double click or a forgotten tab should land where the person really is |
| 2026-10-10 | PRs 7 and 8 combined; history is the survey hub (profile box and a "My surveys" header link); Submit lands on the result | Submit needs a real page to land on; one place for Start, Continue and results. Login still lands on the profile |
| 2026-10-10 | Tier names are placeholder words in one template until the founder names them; dates are day-only in UTC | Easy to rename later; per-person time zones need data we do not collect yet |
| 2026-10-09 | The statements are behind a paywall: a licence (`Entitlement`, any tier 1–3) is one survey attempt plus results at its tier; upgrade in place, retake with another licence; root admin grants by hand until payments exist | Founder's rule; overrides the 2026-10-05 "pay before or after" decision |
| 2026-10-09 | The individual half of `Entitlement` is built in Milestone 2, with a one-to-one from `Response`; Milestone 4 adds the membership half | A throwaway access flag would need removing later; the one-to-one makes one-licence-one-attempt a database rule |
| 2026-10-09 | A person never sees the statements outside an attempt, nor their own answers after submitting; the review page shows a count, the result page shows date, status, tier and results | Founder's rule; overrides FR-19 for the person's own scope |
| 2026-10-09 | Survey scale is 1–4 forced choice, not 1–5; four fixed labels | Founder's questionnaire: no neutral midpoint, every answer commits a direction |
| 2026-10-09 | Five statements a page; Next locks the page for good; no back button; answers still autosave per click | Founder's choice; progress survives a closed browser, and locked pages stop second-guessing |
| 2026-10-09 | The statements are private: placeholder rows in the migration, real wording loaded from a file outside the repository and the image; intro text and labels stay public | Repository and ghcr.io image are public and the founder wants them to stay so; algorithm and insights handled in Milestone 5 |
| 2026-10-09 | `Question.metadata` JSON instead of named columns for per-question attributes | Many per-question fields are expected later; keep them in the private file with no migration each time |
| 2026-10-09 | Each submitted response is kept and listed in history; the membership key waits for Milestone 3 | `Membership` does not exist yet (superseded the same day: retakes need a licence, see above) |
| 2026-10-09 | Milestone 2 split into ten PRs: survey models; entitlements; response model; services; disclosure; pages and autosave; review and submit; history; deploy the private file; docs (superseded the same day by the revised plan below) | Same method as Milestone 1 |
| 2026-10-09 | Erasing an account: no completed survey means hard delete; a completed survey means strip the email, phone, name and login and keep the results, marked `anonymised_at`; irreversible; superuser-only admin button with the typed email and a reason; an account that has used the admin is stripped, not deleted | Founder: mistakes and test accounts leave no trace; survey data is kept for aggregate insights and only the identity goes; the email is free to sign up with again. Replaces the earlier soft-delete-with-reserved-email idea |
| 2026-10-09 | Keep as much as is legally possible (age, gender, company, dates); remove only email, phone and name. Demographics live on `Person`, identity on `Account` and `ContactPoint`. A privacy lawyer decides what is anonymous enough | Founder's rule; keeps the erase code unchanged when demographics arrive |
| 2026-10-09 | A paid licence nobody finished: the account and the licence stay, the data never enters aggregates (only submitted responses count); an erasure request hard-deletes it. No licence expiry; staff get an "unused licences" filter | Founder's rule; expiry brings refund and consumer-law questions for the Phase 3 terms |
| 2026-10-09 | `Response` is PROTECT on account, survey version and licence | An accidental delete is impossible; erasure is the deliberate path |
| 2026-10-09 | Django admin has two levels: superusers see everything including answers; the "Support staff" group sees which questions a response has answered, by position, never the values or the self-report, plus licences, accounts and the funnel. The AWS console and database credentials see everything by nature | Founder's rule: support is for debugging and insight, not for reading answers |
| 2026-10-09 | Any staff may grant, upgrade and revoke licences; each grant records `granted_by`; revoke is logged. Purchases will use the same service in Phase 3. All staff may read questions | Founder's rule; licences are manual until payments exist |
| 2026-10-09 | The Django admin is the operations hub: nontechnical staff handle about 99% of issues there; AWS console and GitHub use stay minimal | Founder's end goal; flag any plan step that needs SSH, AWS or GitHub for repeated work |
| 2026-10-09 | One open draft per account is a database rule (widened to account plus membership in Milestone 3) | Two tabs starting at once cannot both create a draft |
| 2026-10-09 | Self-report is Yes or No, then a required Individual/Company/Other drop-down; no "not sure"; no free text in Milestone 2. The optional match box arrives in Milestone 5 with matching, and is cleared after the attempt unless it linked. Phone matches only flag until phones are verified | Founder's rule: match whenever possible, never hassle users; avoids holding unused free text |
| 2026-10-09 | Funnel events carry no link to an account or person; recorded inside the same transaction as the thing that happened; no backfill; only superusers can delete events (to clear test sign-ups) | Erasing someone must not change the conversion numbers; the live accounts so far are tests |
| 2026-10-09 | Milestone 2's PR plan revised to: 1, 2, 3 merged, 3b erase, 3c funnel, then 4 services, 5 disclosure, 6 pages, 7 review, 8 history, 9 survey wording in the admin (proposed), 10 docs | Soft delete became erase; funnel added; the private file moves into the admin to avoid SSH |
| 2026-10-09 | Verified email collisions are recovered, never auto-linked or auto-merged; Milestone 5 loses its verified-email rule | Recycled and shared inboxes would take over accounts silently; see `02-architecture.md`, "Recovery and recycled contacts" |
| 2026-10-09 | Milestone 1 widened: login with any verified email, make primary, remove email, reset notices, post-verification personal-email prompt, phone country selector | Founder: one account per person across employers in India, US and UK; people rarely return to a profile page |
| 2026-10-09 | allauth verification `mandatory`: no login until the address is verified | Simplest with allauth, and it makes "never log in with an unverified address" automatic; the survey-view guard stays as a second line |
| 2026-10-09 | All allauth URLs mounted under `/accounts/`; own pages shadow login and signup by name; adapter closes allauth's signup | allauth links between its pages by name, so a partial mount risks a missing name at run time |
| 2026-10-09 | Rate-limit counts in a PostgreSQL cache table | The default in-memory cache is per gunicorn worker, so limits would only hold per worker |
| 2026-10-09 | Email-only login is permanent; no username field | Identity rests on verified email; a username could be added later with one column and two settings |
| 2026-10-09 | Phone login and SMS verification deferred past Milestone 1 | Needs a paid SMS provider and per-country sender registration (India DLT takes weeks) |
| 2026-10-09 | Milestone 1 split into eight PRs: models; normalisers and `register`; allauth and verification; layout, signup, login; reset; profile; admin and `verified_email_required`; live check and docs | Small reviewable diffs; each leaves `main` deployable |
| 2026-10-07 | Django 6.1 (current release) rather than 5.2 LTS | Already installed; 6.2 LTS lands April 2027 as a small bump. Note 6.1 uses `MAILERS` instead of `EMAIL_BACKEND` |
| 2026-10-05 | Deploy an empty site before any feature | Isolates infrastructure problems from application problems |
| 2026-10-05 | Individual survey flow before enterprises | Same flow; one nullable key difference; simpler to build once |
| 2026-10-05 | Tenant isolation tests written before the enterprise views | The one bug class that cannot be fixed later cheaply |
| 2026-10-05 | Entitlements built in MVP although nothing filters on them yet | Seat counts are a day-one customer question; Phase 3 writes here |
| 2026-10-05 | Worker and matching after enterprises | Matching rules depend on memberships existing |
| 2026-10-05 | No time estimates | Learning curve makes them unreliable; stalls are the signal instead |
| 2026-10-09 | Signup country selector order is US, India, UK, then A to Z | Founder's choice in PR 4; the earlier text said India, US, UK |
| 2026-10-09 | Password reset links go only to the typed verified address; the notice (no link) goes to the other verified emails at request time; unverified primaries cannot reset | A link to every address would let a recycled old inbox take the account; an unverified primary may be a typo |
| 2026-10-09 | Signup phone is a flag and dial-code picker (intl-tel-input, vendored) replacing the separate country dropdown; the dropdown stays as the no-JavaScript fallback | Founder's choice; the profile's change-phone reuses it |
| 2026-10-09 | Minimum password length 10; live checklists on signup and the new-password page | Founder wanted visible requirements; 8 was low; "too common" and "too similar" stay server-side |
| 2026-10-09 | Login lands on the profile page; the "add a personal email" banner is a nudge remembered by a nullable `Account.personal_email_prompt_dismissed_at`, and the add-email form is always on the profile | The profile is where people manage contacts; "not now" must not remove the ability to add an email later |
| 2026-10-09 | Resending a verification link is limited to one per address per minute (cache); adding an email keeps the address even if the mail server refuses the message | `send_verification` has no limit of its own; SES is sandboxed, so a failed send must not lose what the person typed |
| 2026-10-09 | The profile page is not behind `verified_email_required`; the guard goes on survey and enterprise views from Milestone 2 | An unverified account must be able to reach the profile to request a verification link or add an email |
| 2026-10-09 | The Django admin never edits contacts directly; `ContactPoint` is read-only there, with actions that call `make_primary` and `remove_contact` | A contact lives in our `ContactPoint` and in allauth's `EmailAddress`; a plain admin edit would change one and leave the other behind |
