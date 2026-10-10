# Build Plan — Survey Platform

As of 2026-10-05 · Planning Session 5 · Depends on all four earlier docs · Milestone 2 and later revised 2026-10-09 · Milestone 2 status synced 2026-10-10

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

**Run the worker locally always.** Keep `run_worker` running in a second terminal from milestone 5 on. If you forget, jobs silently queue up and features look broken.

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

- [ ] A stranger can sign up on the live site, receive the email, verify, log in and log out on a phone. *(Waiting on SES production access; until then only verified addresses receive mail. See "Open follow-ups".)*
- [ ] Password reset works on the live site, from a second verified email too. *(Needs a second address SES can deliver to; see "Open follow-ups".)*
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

**Status (2026-10-10).** Code-complete and deployed. Merged: PR 1 survey models and `load_questions` (#31), PR 2 licences (#32), PR 3 the `Response` model and the two-level admin (#33), PR 3b erasing an account (#34), PR 3c the funnel (#35), PR 4 response services (#37), PR 5 the start page and the licence gate (#38), PR 6 statement pages with autosave (#39), PRs 7 and 8 combined: review, submit, history and result (#40), PR 9 the survey wording in the admin (#42), PR 10 docs and the last small fixes (#43). 457 tests. Left: PR 11, the founder's live checks (the tasklist at the top of "Open follow-ups"), then a docs-only change that ticks the "Done when" boxes they confirm. "All tests pass" is ticked; the other boxes are live checks. The PR plan below is the revised one agreed with the founder; the original ten-PR list is superseded.

**The product rules, as specified by the founder**

- The Accelerare Personality Diagnostic: 25 statements, each rated 1–4 (forced choice, no midpoint). The four labels are fixed for every statement: 1 "This does not describe me", 2 "This slightly describes me", 3 "This mostly describes me", 4 "This describes me very accurately" (full sentences in the template).
- Five pages of five statements, in position order. Within a page the person may change any of the five answers. Clicking **Next** locks the page; locked answers can never be changed, and there is no back button.
- Progress is saved on the server: every click is saved as it happens, and the response remembers how many pages are locked. Closing the browser, an outage or a new device resumes on the first unlocked page with the saved clicks selected.
- **Licences.** Registering is free, but the statements sit behind a paywall. A licence (the `Entitlement` row from the architecture doc) is one survey attempt plus the results at its tier. Any tier (1–3) unlocks the survey. Upgrading a licence raises its tier in place, so the same response shows more results. A retake needs another licence. Until payments exist (Phase 3), root admin grants licences by hand in the Django admin after invoicing. Enterprises buying licences in assorted tiers for their members is Milestone 4.
- **Tier 0.** An account with no active licence is at "tier 0", the free tier. That is a display state, not a licence row: the history and result pages show what a free account gets. The founder's suggestion for Milestone 5 is sample or limited insights from the purchasable tiers; the content is undecided.
- **What a person sees.** With or without a licence: their account, their survey history (each response with date, status and tier) and, from Milestone 5, the results and insights their tier allows. Never, at any tier: the statements outside an attempt in progress, or their own answers once submitted. Root admin keeps the read-only Django admin view of answers. Whether enterprise administrators see answers is undecided; see "Open follow-ups".
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
- The disclosure text names the viewer: "your answers will be visible to you and to Accelerare" for individuals; milestone 3 adds "and to <enterprise name>'s administrators."

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

*Still to do:*

11. `m2-live-checks` (the founder, then a docs-only PR): work through the tasklist at the top of "Open follow-ups"; the PR ticks the Milestone 1 and 2 "Done when" boxes the results confirm and moves finished follow-ups to the decision log. Milestone 2 is closed when its boxes are ticked.

**Done when**

- [ ] On the live site, a verified account without a licence sees the notice and cannot reach a statement; after root admin grants a licence in the admin, the same account can take the survey on a phone, close the browser mid-way, reopen, resume on the right page, and submit.
- [ ] The live site shows the real statements, not placeholders, and the public repository contains none of them.
- [ ] After submitting, the response appears in history with its tier, no page shows the answers, and a second attempt needs a second licence.
- [ ] Root admin sees the response in the admin, read-only; a Support staff account sees which questions are answered but not the values.
- [ ] On the live site, a test account is erased from the admin both ways (one with no completed survey, one with a completed survey) and the same email can sign up again.
- [ ] The funnel page in the admin shows the live sign-ups, verifications, licences and survey events.
- [x] All tests pass. *(457 passed, ruff, `check --fail-level WARNING` and `makemigrations --check` clean, 2026-10-10.)*

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

## Milestone 3 — Enterprises, memberships, invites and codes

**Goal:** anyone can create an enterprise and become its admin; admins can invite by email or issue codes; people join through either; admins see a table of their members' responses and each response in full; nothing from one enterprise is ever visible to another.

**What you build**

- `apps/enterprises/models.py`: `Enterprise` (name, slug unique, created_by FK, created_at), `Membership` (account FK, enterprise FK, role member/admin, status active/deactivated, joined_at, joined_via_invite FK nullable, joined_via_code FK nullable; unique on account+enterprise), `Invite` (enterprise FK, email, token unique, tier nullable, expires_at, accepted_at nullable, revoked_at nullable, created_by FK), `JoinCode` (enterprise FK, code unique, tier nullable, max_uses, uses, expires_at, revoked_at nullable, created_by FK).
- `apps/enterprises/services.py`: `create_enterprise(account, name)`, `invite_by_email(admin_membership, email, tier=None)`, `accept_invite(token, account)`, `create_code(admin_membership, max_uses, expires_at, tier=None)`, `redeem_code(code, account)`, `revoke_invite`, `revoke_code`, `deactivate_membership`.
- `apps/enterprises/scoping.py`: `for_admin(request, slug) -> Membership` which loads the active admin membership for the logged-in account and that slug, or raises `PermissionDenied`. Every enterprise view starts by calling it.
- Views and templates under `/enterprise/`: `create.html`, `dashboard.html`, `members.html` (list with status, tier, joined date; deactivate button), `invites.html` (list, create, revoke), `codes.html` (list with uses/max, create, revoke), `responses.html` (filterable, sortable table: member, status, date, tier, possible_repeat flag), `response_detail.html`.
- Join pages: `/join/invite/<token>/` and `/join/code/` (enter code; if not logged in, sign up first then redeem). After joining, the member's survey start page reads "visible to you, to <enterprise> administrators, and to <platform>."
- `Response.membership` now set when the survey is started from the enterprise context; the member's own list shows context per response.
- Email: the invite email, sent via a job in milestone 5; until then sent synchronously.
- Django admin (the hub): `Enterprise`, `Membership`, `Invite` and `JoinCode` registered for staff, with a "deactivate membership" action that calls the service, so support never needs the shell.

**Technical detail**

- *Carried over from Milestone 2.* The database rule "one open draft per account" (`response_one_open_draft_per_account`) becomes one per account and membership, in a new migration. Sign-up events from invites and codes record the funnel channel `invite` or `code` (it is `direct` until then). Enterprise reports show two views: current members (active memberships) and the historical total (including deactivated members and accounts erased with `anonymised_at`).
- *Erasure and memberships (open).* `erase_account` strips the identity and keeps the person, but a membership links a person to a workplace, which can identify them. Decide with the privacy lawyer whether erasing a person also cuts their membership link, and how an enterprise's own request to delete its members' data works. The strip list is one function (`erasure._anonymise`), so the answer is a small change.

- Tokens and codes: generate with `secrets.token_urlsafe(32)` for invite tokens; for human-entered codes use a 10-character alphabet without ambiguous characters (no `0/O`, `1/I/l`), uppercase, grouped as `XXXXX-XXXXX`. Store uppercase; compare case-insensitively.
- `accept_invite` and `redeem_code` run inside `transaction.atomic()` and lock the invite/code row with `select_for_update()` so a shared code cannot exceed `max_uses` under concurrent redemptions. Check: not revoked, not expired, uses < max_uses, account has no existing membership in that enterprise (if deactivated, reactivate rather than duplicate).
- Accepting an invite requires the logged-in account to have the invited email as a *verified* contact point. Otherwise show "this invite was sent to x@y; log in with that address or add and verify it."
- Code redemption accepts any email. That is the documented trade for the convenience of shared codes.
- Tier on invite/code creates an entitlement in milestone 4; in this milestone, store the field and ignore it.
- Enterprise self-registration creates the enterprise and the first admin membership in one transaction. No approval step.
- Deactivation sets `status = deactivated`; responses keep their `membership_id`; the admin responses table still shows them, marked as former member.
- Scoping: the enterprise slug is in the URL for navigation only. `for_admin()` verifies that *this account* has an *active admin* membership for *that slug*; the returned membership's `enterprise` is then the only enterprise id used in any query in that view. The slug is never trusted on its own.
- Table filtering and sorting via query parameters (`?status=submitted&sort=-submitted_at`) rendered by HTMX into the table body; validate the sort field against an allow-list.

**Tests**

- Tenant isolation (the most important tests in the project): create enterprises A and B with one admin and two members each, each member with a submitted response. Assert that A's admin, hitting `members`, `responses`, `response_detail` for a B response, and (later) `export`, sees nothing from B — `response_detail` returns 404, not 403, so that B's ids are not even confirmed to exist. Assert that B's member cannot access A's admin pages at all.
- A member (non-admin) of A cannot open A's admin pages.
- Invite: accept with the matching verified email succeeds once; second accept fails; expired, revoked, and wrong-email cases fail with the right messages.
- Code: `max_uses = 2`, three concurrent redemptions (use threads in the test or sequential with the lock asserted) yield exactly two memberships; revoked and expired codes fail; a deactivated member redeeming reactivates rather than duplicates.
- Deactivated member: still sees own responses; admin still sees them.
- Enterprise create: creator becomes admin; a second create by the same account creates a second enterprise and a second admin membership.
- Erasing an account that has a membership follows the rule decided above, and a former member's results still count in the historical total.

**Done when**

- [ ] On the live site: create an enterprise, generate a code, open an incognito window, sign up and join with the code, take the survey, and see that response in the admin table and detail page.
- [ ] Same with an email invite.
- [ ] Deactivate that member; they still see their response, you still see it.
- [ ] All tenant isolation tests pass.

**Why this order / what to understand**

This is where the project becomes multi-tenant, and multi-tenancy is where products leak data. The single most valuable thing in this milestone is `scoping.for_admin()` and the tests that prove it works. Read that function slowly.

*The threat model, plainly.* An attacker signs up, creates their own enterprise, and now has an admin page. They look at the URL, `/enterprise/their-slug/responses/42/`, and change `their-slug` to `acme`, or change `42` to `41`. If any view takes the enterprise from the URL and trusts it, or loads response 41 without checking that it belongs to the admin's enterprise, Acme's data is on the attacker's screen. The scoping helper makes this structurally impossible: the only enterprise id in scope comes from the attacker's own membership, so filtering by it returns nothing of Acme's. The 404-not-403 rule stops the attacker learning which ids exist.

*Why invites and codes rather than domains.* Covered in the architecture doc, but worth repeating here because you'll be tempted to add a "join if your email ends in @acme.com" shortcut. Don't. It reintroduces the fake-enterprise problem and buys little, since the admin can send invites to the whole staff list in one go.

*Why locking matters for codes.* Two people redeem the last seat of a `max_uses=10` code at the same instant. Both read `uses = 9`, both write `uses = 10`, and you have eleven members on a ten-use code. The row lock makes the second redemption wait for the first and then see `uses = 10`. Seat pools in the next milestone have the same shape and the same fix.

*The admin table is a real product surface.* Enterprise customers will judge the product by this page. Keep it simple, but make filtering, sorting and the empty state work properly. "No responses yet. Invite members to get started" with a link beats a blank table.

---

## Milestone 4 — Seat pools and entitlements

*Re-plan this section before starting it. On 2026-10-09 the founder decided that a licence is one survey attempt plus results at its tier, and Milestone 2 built the individual half of `Entitlement` with a one-to-one from `Response`. So a seat here is a licence an enterprise bought and assigned to a member, consumed by that member's one attempt, and upgradeable in place; the "joined without a seat" warning becomes "cannot take the survey until given a licence".*

*State after Milestone 2.* `Entitlement` exists with a non-null `person`, source purchase or manual, and `grant_individual`, `revoke`, `change_tier`, `unused_licence` and `has_survey_access` are built, with an admin grant form (the account picker is a plain dropdown), a revoke action and an unused-licences filter. This milestone makes `person` nullable, adds the membership FK, the exactly-one check constraint and the source `seat`, and records the funnel event `licence_granted` with source `seat`. Licences do not expire. Staff manage `SeatPool` from the admin like everything else.

**Goal:** root admin sets seat pools per tier for an enterprise; enterprise admins assign tiers to members within the pool; invites and codes that carry a tier consume a seat on join; an individual can hold an entitlement set manually by root admin.

**What you build**

- `apps/entitlements/models.py`: `SeatPool` (enterprise FK, tier 1–3, seats; unique on enterprise+tier), `Entitlement` (person FK nullable, membership FK nullable, tier, source seat/purchase/manual, granted_by FK, granted_at, revoked_at nullable; check constraint: exactly one of person/membership set).
- `apps/entitlements/services.py`: `set_seat_pool(enterprise, tier, seats)` (root only), `assign_seat(admin_membership, member_membership, tier)`, `revoke_seat(...)`, `grant_individual(person, tier, source)`, `current_tier(membership) -> int | None`, `current_tier_for_person(person) -> int | None` (highest active), `seats_used(enterprise, tier)`.
- Enterprise admin: a tier column and a change-tier control on the members page, showing "3 of 10 tier-2 seats used."
- Root admin: `SeatPool` and `Entitlement` in Django admin; a custom action on `Enterprise` to set all three pools at once.
- `accept_invite` and `redeem_code` now call `assign_seat` when a tier is present; if the pool is full, the join still succeeds and the admin page shows a warning banner "2 members joined without a seat because the tier-2 pool is full."

**Technical detail**

- `assign_seat` runs in a transaction, locks the `SeatPool` row, counts active entitlements for that enterprise and tier, and refuses if `count >= seats`. Changing a member's tier revokes the old entitlement and creates a new one in the same transaction, so a downgrade frees a seat and an upgrade needs one.
- Revocation is a timestamp, not a delete: the history of who had which tier when is preserved, and an audit row is written (milestone 5 formalises the audit log; until then write the row directly).
- "Current tier" for display is computed, not stored on the member: highest tier among active entitlements on the membership. For the individual context, highest among the person's active entitlements.
- Seat pools can be reduced below current usage by root admin (e.g. a customer downsizes). Allow it, show the enterprise admin "12 of 10 seats used; revoke 2 to assign new seats," and refuse new assignments until it's back under.

**Tests**

- Pool of 2: third assignment refused; concurrent assignments (threaded) yield exactly two.
- Change tier 1 → 2 frees a tier-1 seat and consumes a tier-2 seat atomically; if tier-2 is full, nothing changes.
- Code with tier joins consume seats; when the pool is full, join succeeds, entitlement absent, warning shown.
- Revoked entitlement not counted; `current_tier` returns None.
- Individual manual grant shows on the person's response list as their tier.
- Enterprise A's admin cannot assign a seat to B's member (scoping again).

**Done when**

- [ ] Root admin sets pools in the admin; enterprise admin assigns and changes tiers on the live site; counts are correct.
- [ ] A code carrying tier 2 consumes a seat on join.
- [ ] All tests pass.

**Why this order / what to understand**

Nothing in the MVP *shows* a tier-filtered result yet, so it's fair to ask why build entitlements now. Three reasons: enterprises will ask "how many seats have I used" from the first conversation; the invite/code-with-tier flow needs it; and this is the table payments will write into in Phase 3, so its shape should be settled by then.

*Entitlement versus "tier on the member."* A single `tier` column on Membership would be simpler today and wrong by Phase 3. Entitlements have a source (seat, purchase, manual), a grantor, a timestamp and a revocation; that's what an invoice dispute or a refund needs. They also let an individual purchase and an enterprise seat coexist for one person without conflict.

*Why computed, not cached.* Storing `current_tier` on the membership means two places can disagree. Computing it from entitlements is one query with an index and is always right. Cache it only if a profiler ever says to.

---

## Milestone 5 — Background jobs, matching, audit log

**Goal:** slow or failure-prone work runs outside web requests; the matching rules run on verification and submission, auto-link on verified email, flag on weaker signals; root admin reviews and can undo; every admin action is audited.

**What you build**

- `apps/jobs/models.py`: `Job` (kind, payload JSON, status queued/running/done/failed, attempts, max_attempts default 5, run_after, locked_at nullable, last_error text, created_at). `jobs.enqueue(kind, payload, run_after=None)`. A registry decorator `@job("kind")` that maps kinds to handler functions.
- `apps/jobs/management/commands/run_worker.py`: a loop that, inside a transaction, selects the oldest queued job with `run_after <= now()` using `select_for_update(skip_locked=True)`, marks it running, commits, runs the handler, then marks done or schedules a retry with backoff (`2 ** attempts` minutes) or failed after max attempts. Sleeps one second when idle. Handles `SIGTERM` by finishing the current job and exiting.
- Handlers: `send_email(kind payload: template, to, context)`, `run_matching(account_id | response_id)`, `compute_result(response_id)` (no-op in MVP but wired), later `export_csv`.
- `apps/matching/rules.py`: each rule is a function `(account) -> list[Candidate]` returning the other account ids and the signals that fired. Rules: verified phone match (auto-link, inert until SMS verification), unverified phone match (flag), self-report-plus-prior-response (flag, also sets `possible_repeat`), name-plus-memberships (flag). There is no verified-email rule: a verified email has one owner by constraint, and a second claim is handled by the Milestone 1 recovery flow (optionally recording a `flagged` candidate). Thresholds and the list of enabled rules in one `RULES` constant.
- `apps/matching/models.py`: `MatchCandidate` (account_a, account_b, signals JSON, status auto_linked/flagged/confirmed/rejected, resolved_by nullable, resolved_at nullable; unique on the unordered pair). `apps/matching/services.py`: `run_for_account`, `auto_link(a, b)` (moves `b.person` to `a.person`, marks the old person `merged_into`), `confirm(candidate, actor)`, `reject(candidate, actor)`, `unlink(candidate, actor)` (reverses: creates or restores a separate person for b).
- `apps/audit/models.py`: `AuditLog` (actor FK nullable, action, target_type, target_id, detail JSON, at). `audit.record(actor, action, target, detail)` called from every admin-facing service in the same transaction.
- The self-report match box. Milestone 2 asks only Yes or No and how the survey was taken (individual, company, other). This milestone adds the optional box "anything that would help us find your earlier results" (an email or phone number), shown after a Yes and skippable with no consequence. It is used by the matching attempt and then cleared, unless it led to a link; erasing a person clears it too; only superusers can see it. A Yes with nothing to match is simply left alone: matching stays automatic on verified data, and no one is hassled.
- Root admin: a `MatchCandidate` admin list filtered to flagged by default, with actions confirm/reject/unlink, each writing audit rows. Enterprise admin responses table shows the `possible_repeat` flag.
- `submit` now enqueues `run_matching` and `compute_result`; verification now enqueues `run_matching`; invite emails go through `send_email`.

**Technical detail**

- `skip_locked` is what lets two workers run safely later. One worker now; the code already supports more.
- Idempotency: `run_matching` for an account that already has candidates recorded must not duplicate them (the unique pair constraint plus `get_or_create`). `send_email` is the one handler that is not naturally idempotent; accept that a retry after a crash *during* send may double-send, and keep retries conservative.
- Name normalisation for the weak rule: lowercase, strip diacritics, collapse whitespace, compare full name only. Do not attempt fuzzy matching in the MVP.
- Phone matching: phone numbers are unverified until SMS verification exists, so a phone match creates a flagged candidate for staff to review in the admin and never links accounts on its own; once phones are verified a verified phone matches automatically like email. The `took_before_via` answer is a hint for where to look (a company answer points at enterprise memberships).
- Audit: until `AuditLog` exists, the Django admin's own history (`LogEntry`) records licence grants, revokes and account erasures (the erase action writes its entry by hand under the label "Account #id" so the history holds no email). `AuditLog` must cover those actions systematically, and `erase_account` writes an `AuditLog` row.
- Auto-link must never run on an unverified contact point. The rule reads `verified_at IS NOT NULL` and the test asserts it.
- `unlink` is the hardest function here. Define it as: candidate must be auto_linked or confirmed; give `account_b` a fresh Person (or its original one if `merged_into` points back cleanly); move any person-level entitlements granted *after* the link back only if they were granted explicitly to b (keep a `granted_to_account` hint on Entitlement for this). Write the decision in the audit detail. Keep it simple and documented rather than clever.
- Worker in production is the `worker` container from the infrastructure doc. Locally, a second terminal. Add a `/health` detail that reports the age of the oldest queued job so a stuck worker is visible.

**Tests**

- Worker: enqueue three jobs, run one loop iteration three times, all done in order; a handler that raises is retried with increasing `run_after` and marked failed after five attempts with the error text stored.
- Email: a second account attempting to verify an already-verified email is refused by the constraint and sees the recovery page; nothing is linked. Same email but one unverified → nothing.
- Phone rule: same verified phone links; same unverified phone flags only.
- Self-report: a submission with `took_before=True` by an account with an earlier submitted response sets `possible_repeat` and creates a flagged candidate.
- Name rule: same name, both with memberships → flagged; same name, no memberships → nothing.
- Confirm, reject and unlink each write an audit row; unlink leaves the two accounts with distinct persons.
- Enterprise admin sees the `possible_repeat` flag but nothing about the other account.

**Done when**

- [ ] Worker container runs on the server and processes an email job; the invite email now arrives via the worker.
- [ ] Two test accounts with the same verified email become one person on the live site; root admin can unlink them.
- [ ] Audit log shows every admin action taken so far.
- [ ] All tests pass.

**Why this order / what to understand**

*Why a job queue at all.* Submitting a survey should take 200 milliseconds and never fail. Matching might take a second; email might take five seconds or fail because the mail server is down. If those run inside the submit request, the user waits, or sees an error for a submission that actually saved. Moving them to a queue decouples "the user's action succeeded" from "the follow-up work happened." The follow-up can retry; the user is already on the thank-you page.

*At-least-once and idempotency.* A worker can crash after running a job but before marking it done. The job runs again. So every handler must be safe to run twice. "Compute the result for response 42" is safe (same input, same output, overwrite). "Send an email" is not, which is why email is the one place you accept a small risk rather than engineering exactly-once delivery.

*Why the rules are data-shaped.* `RULES` is a list you can edit. When the founder decides name matching is too noisy, you remove one entry; nothing else changes. When phone verification ships, the phone rule starts firing with no code change because it already checks `verified_at`.

*Why audit is in the same transaction.* An audit row that says "deleted account 7" written *after* the delete committed can be lost if the process dies in between, and then there is no record. In the same transaction, either both happen or neither.

---

## Milestone 6 — Root admin, CSV export, deletion

**Goal:** root admin can see and search everything, export any scope as CSV, delete an account on request with an audit stub; enterprise admins can export their scope.

**What you build**

- Django admin polish: list displays, search fields and filters on every model; `Response` read-only after submit; inline `ContactPoint` under `Account`; inline `Membership` under `Enterprise`; links between related objects.
- `apps/exports/views.py`: `enterprise_export(request, slug)` (via `for_admin`) and `root_export(request)` (staff only). Both stream a CSV with `StreamingHttpResponse` and a generator: one row per submitted response with columns `response_id, submitted_at, survey_version, enterprise, member_email, tier, took_before, possible_repeat, q1..q25`.
- Erasure. *Built in Milestone 2, PR 3b* as `apps/accounts/erasure.erase_account` with an admin button and confirmation page: hard delete when there is no completed survey, otherwise strip the identity and keep the results. This milestone adds what remains: the `AuditLog` row with a summary of what was removed, the handling of memberships and enterprise-level requests (see Milestone 3), results rows once they exist, and a written compliance procedure (who may request, the response deadline, what is kept and why, and how long hard-deleted data stays in database backups).
- A root dashboard page (or admin index customisation) with counts: accounts, enterprises, responses submitted this week, flagged candidates awaiting review, failed jobs.

**Technical detail**

- CSV rows come from a queryset iterated with `.iterator()` inside the generator so a 50,000-row export does not load into memory. Column order for q1..q25 comes from the survey version's questions by position, so the header is stable.
- Export scope for enterprise admins is the scoped queryset from milestone 3; the view adds nothing.
- Tier in the export is the computed current tier at export time (entitlements), consistent with the UI.
- Deletion must handle a merged person: if the deleted account's person has other accounts, the person survives and only the account's own rows go. Document this in the confirmation page.
- Django admin is staff-only; `is_staff` is set only by `createsuperuser` or by another superuser. There is no self-serve path to it.

**Tests**

- Export for enterprise A contains exactly A's submitted responses with 25 question columns in position order; B's rows absent; drafts absent.
- Root export contains both.
- Erase: all expected rows gone (or stripped, for an account with a completed survey), audit row present with the counts; a merged person survives when another account remains; results rows follow the same two outcomes.
- Non-staff cannot reach `/admin/` or `root_export`.

**Done when**

- [ ] Export downloads from both admin surfaces on the live site and opens cleanly in a spreadsheet.
- [ ] A test account is deleted via the admin action and its audit stub is visible.
- [ ] All tests pass.

**Why this order / what to understand**

*Django admin is your root console.* It is not pretty, and customers never see it, so that's fine. It saves you building a dozen CRUD screens. Spend time on search fields and list filters; those are what make it usable at a thousand accounts.

*Streaming versus building the file.* Building the full CSV in memory and then returning it works until the first big enterprise. A generator writes rows as they are read; memory stays flat and the download starts immediately. It's a two-line difference now and a rewrite later.

*Deletion is scary on purpose.* It is the one irreversible action, so it has a confirmation page, a reason field, a transaction, and an audit stub. The DPDP obligation is to delete on request; the operational obligation is to be able to say exactly what was deleted and when.

---

## Milestone 7 — Hardening and pilot launch

**Goal:** the site is safe to put in front of a real customer: security settings verified, backups restorable, monitoring live, error pages in place, performance sane for a few hundred users.

**What you build**

- `python manage.py check --deploy` passes with no warnings in production.
- Custom `404.html` and `500.html` in the site's design; `500.html` must not use anything that could itself fail (no database queries in the template context).
- Sentry: confirm both `web` and `worker` report; add the account id as user context; set `send_default_pii = False`.
- Rate limiting on the join-code endpoint (brute-force protection): limit attempts per IP and per account; allauth's limiter pattern or `django-ratelimit`.
- Backup restore test from the infrastructure runbook, with the date recorded.
- Uptime monitor on `/health`; CloudWatch alarms; billing alert confirmed.
- Load sanity check: use a simple script to create 500 accounts and 1,000 responses locally; verify the admin tables and exports stay responsive (sub-second). Add database indexes where the ORM queries show sequential scans (`EXPLAIN` in the Django shell).
- Privacy text: the disclosure page and a short privacy page naming what is stored, what is kept after an erasure request (the survey results, with the identity removed) and how to request erasure. A privacy lawyer reviews it before the pilot: what counts as anonymous enough for what we keep (age, gender, company and exact dates can identify someone in a small company), the US, UK and India rules, and the enterprise data agreements.
- Backups and erasure: confirm the RDS backup retention (30 days) and state in the procedure how long an erased account can remain in a backup.
- `NOTES.md` and the infrastructure runbook updated with every deviation made during setup.
- A pilot checklist with the first enterprise: create their enterprise, set pools, send invites, watch the first ten submissions in the admin table, check Sentry after the first day.

**Done when**

- [ ] `check --deploy` clean; error pages render; Sentry receives from web and worker.
- [ ] Restore test done and dated.
- [ ] Monitors fire when you stop the web container (test it once, then restart).
- [ ] 1,000-response local dataset: admin table, filters and export all feel instant.
- [ ] First pilot enterprise onboarded.

**Why this order / what to understand**

*Hardening last, not never.* Each earlier milestone already applied the standards from the opening section; this milestone verifies them as a whole and adds the things that only make sense once the product is complete. It is not the milestone where security starts.

*The restore test is the backup.* A backup you have never restored is a hope. Doing it once, before any customer, turns it into a procedure you've run. The runbook has the steps.

*Monitoring is three things.* Sentry tells you a request failed. The uptime check tells you the site is down (Sentry can't, because nothing is running to report). CloudWatch tells you the disk is full or the database is out of storage before the site goes down. You want all three and they're all free at this scale.

*Why a load script.* "It's fast with my five test rows" says nothing. Five hundred users is small, but a missing index can turn a 10 ms query into 2 seconds at that size, and the admin responses table is the page customers watch. Generating realistic data once and clicking around is the cheapest performance test there is.

---

## Phase 2 stub — the algorithm seam

Not a milestone, but worth doing in milestone 5 when the worker exists:

- `apps/results/models.py`: `Result` (response FK, algorithm_version, payload JSON, computed_at). `apps/results/algorithm.py`: `ALGORITHM_VERSION = "0.0.0"` and `compute_result(response) -> dict | None` returning `None`. The `compute_result` job calls it and stores a row only if the return is not `None`.
- `apps/results/tiering.py`: `visible_fields(payload, tier) -> dict`, currently returning everything; the tier map is a dictionary from field name to minimum tier, filled in when the algorithm's output shape is known.
- A management command `recompute_results --version X` that enqueues `compute_result` for every submitted response, for re-runs.

When the algorithm arrives, Phase 2 is: implement `compute_result`, fill the tier map, build the results page that reads `Result` rows and calls `visible_fields`. Nothing in milestones 0–7 changes.

---

## Phase 3 stub — payments

Not a milestone. Self-serve purchase for individuals and enterprises (likely Razorpay for India) writes licences through the same services the admin uses: `grant_individual` with source `purchase`, and the seat-pool services. Already decided: licences do not expire, a retake needs another licence, upgrades happen in place. Needed when payments arrive: a payment ledger (amount, currency, date, invoice number, provider reference, the licence id and tier) that carries no personal identity, so erasing a person never removes an accounting record; refunds revoke the licence through the service; the funnel records `licence_granted` with source `purchase`; and a reminder path for unused licences once the worker exists. Nothing in milestones 0–7 changes.

---

## Milestone map

| # | Milestone | Depends on | Deployable result |
| --- | --- | --- | --- |
| 0 | Foundations and first deploy | — | Empty site on HTTPS with CI/CD |
| 1 | Accounts | 0 | Sign up, verify, log in, reset |
| 2 | Survey and responses | 1 | Individuals take and view the survey; licences, erasure and the funnel are built (PRs 1 to 8 merged; 9 and 10 left) |
| 3 | Enterprises, memberships, join | 2 | Enterprise admins onboard members and view responses |
| 4 | Seat pools and entitlements | 3 | Tiers assigned and counted |
| 5 | Jobs, matching, audit | 4 | Worker live; repeats flagged and linked; actions audited |
| 6 | Root admin, export, erasure audit | 5 | Root console complete; CSV; erasure audited and documented |
| 7 | Hardening and pilot | 6 | First customer |

## When to stop and ask

Ask for help (here, or anyone experienced) rather than pushing on when:

- Milestone 0's deploy has eaten more than a couple of days. It's almost always one networking or TLS detail and a second pair of eyes finds it fast.
- A tenant-isolation test is hard to make pass. That's the one place where "I'll fix it later" is not acceptable.
- You're about to write raw SQL, a custom migration operation, or anything with the word "clever" in your head.
- Something works locally and not on the server. The difference is always in configuration; compare `.env` to `.env.example` first.

## Open follow-ups

Things agreed but not done, so they are not forgotten. Move a line to the decision log or delete it when it is finished.

**Milestone 2 PR 11: the founder's tasklist** (live site, top to bottom. Report the results in a new chat; PR 11 then ticks the "Done when" boxes they confirm.)

*A. Load the real survey wording (Done when 2)*
- [ ] Save the master copy of `survey_v1.json` in a password manager or private drive. It is never committed.
- [ ] Admin → Survey versions → Survey version 1 → "Load the survey wording…". Paste the JSON or choose the file and press Check: expect "changes the wording of 25". Press Apply. The version's History shows who did it and the counts, never the wording.
- [ ] On the laptop, in the project folder, check the public repository holds none of the statements. This prints how many statements appear anywhere in the git history and must print 0: `uv run python -c "import json,subprocess;d=json.load(open('private/survey_v1.json'));print(sum(1 for e in d if subprocess.run(['git','log','--all','--format=%h','-S',e['text']],capture_output=True,text=True).stdout.strip()))"`

*B. Take the survey on a phone (Done when 1 and 3)*
- [ ] With a verified test account that has no licence (use `admin@theaccelerare.com`, which SES can deliver to): the start page shows the "you need a licence" notice and no statement page opens.
- [ ] Grant it a licence: Entitlements → Add, type part of the email in the Account search box, tier 1, source manual.
- [ ] On a real phone: start, answer page 1 and part of page 2, close the browser, reopen, and check it resumes on page 2 with the saved ticks and shows the real wording. Finish and submit.
- [ ] My surveys shows the response with its tier, no page shows the answers, and Start asks for a second licence.
- [ ] Revoke that licence in the admin; the result now shows "Free (licence withdrawn)".

*C. The admin (Done when 4 and 6)*
- [ ] As superuser, the response is read-only and shows the answers.
- [ ] Make a Support staff account: sign up a second test account (its email need not be verified to use the admin), then in the admin tick "Staff status" and add it to the "Support staff" group. Logged in as it: licences, accounts, the funnel and the answered positions on a response are visible; the answers, Erase, delete and "Load the survey wording…" are not.
- [ ] The funnel page shows the live sign-ups, verifications, licences and survey events.

*D. Erase (Done when 5)*
- [ ] Erase a test account with no submitted survey (it is deleted) and one with a submitted survey (it is stripped, results kept); read the confirmation page each time. Then sign up again with the same email.

*E. Milestone 1 browser checks*
- [ ] Live signup with an address SES has not verified: "check your inbox" plus a yellow warning, and the same warning on login. Use `admin@theaccelerare.com` for the live tests, in an incognito window.
- [ ] Signup: submit empty, type in a box, its red error vanishes.
- [ ] Admin: search an account by phone; make-primary and remove on a secondary email; removing a primary shows a red refusal. Then tick "Root admin can find an account by email or phone".
- [ ] Profile page: stored `+number` picks the right flag; "Not now" banner. *(Phone box width and spacing at phone width were checked by headless screenshots in #27; the open flag dropdown was not.)*
- [ ] Live add-email, signup to login, and the reset pages in a real browser.

*F. A second email address (Milestone 1 boxes 2 and 3)*
- [ ] Verify one or two of the new business addresses as SES email identities (AWS console). While SES is sandboxed they are the only way to receive mail on a second address.
- [ ] Use them: password reset from a second verified email; make a second email primary, log in with it and remove the old one.

*G. Setup*
- [ ] Register `/health` with an uptime checker (`04-infrastructure.md`, step 8.4).

**Waiting on SES production access** (a pending AWS support case; see `04-infrastructure.md`, "Email sending")
- [ ] Live signup by a stranger, verify, log in and out on a phone (Milestone 1, first "Done when" box).
- [ ] Re-test every email flow with a real outside address once approved.

**Carried over: open decisions that do not block Milestone 2**
- [ ] Name the tiers. Today they show as "Tier 1/2/3" and "Free" (placeholder words in `templates/responses/_tier.html`, one file to change).
- [ ] Before Milestone 3: do enterprise administrators see members' answers, or only results? (The founder ruled on 2026-10-09 that the person never sees their own answers after submitting; FR-19 is overridden for that scope only. Root admin keeps the read-only Django admin.) And what happens when a company asks for its members' data to be deleted (see the note in Milestone 3 on memberships).
- [ ] For Milestone 5: what tier 0 (no licence) shows on the result page (sample insights from the paid tiers, a limited subset, or just the invitation to buy), and how the algorithm and the insights stay private (a second private repository installed as a package, which makes the ghcr.io image private and needs `docker login` on the server, or a file loaded at run time).
- [ ] Privacy lawyer before launch: is "strip email, phone and name, keep the results and demographics" anonymous enough in the US, UK and India; what the privacy text must say; backup retention after an erasure; enterprise data agreements; and whether to offer a user-facing "delete my account" button and its wording (staff erase from the admin for now).
- [ ] Later, when needed: split "Support staff" into a debugging group and a business-insights group (already two named lists in `apps/responses/signals.py`), and decide then whether they should read the statements (today they can, through the read-only Questions and Survey versions pages; the founder is fine with that for now); the payment ledger without identity and the refund path (Phase 3); and revisit the UTC, day-only dates on history and result if people far from UTC are confused.

**Small code and docs follow-ups**
- [ ] The README is being written by the founder separately.

## Decision log

| Date | Decision | Reason |
| --- | --- | --- |
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
