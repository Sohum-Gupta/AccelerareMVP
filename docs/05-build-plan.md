# Build Plan — Survey Platform

As of 2026-10-05 · Planning Session 5 · Depends on all four earlier docs

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

**Goal:** a verified individual can read the disclosure, answer the self-report question, answer 25 questions with autosave, leave and resume, submit, and view their own responses. Submitted responses are immutable.

**What you build**

- `apps/survey/models.py`: `SurveyVersion` (number, published_at, question_count), `Question` (survey_version FK, position, text, min_value, max_value). `survey/fixtures/v1.json` with the 25 questions, loaded by a data migration. A helper `survey.services.current_version()`.
- `apps/responses/models.py`: `Response` (account FK, membership FK nullable, survey_version FK, status draft/submitted, answers JSONField default dict, took_before bool nullable, took_before_where text, started_at, submitted_at nullable, possible_repeat bool default False). A `Meta` constraint: `submitted_at` is null if and only if status is draft.
- `apps/responses/services.py`: `start_response(account, membership=None)` (reuses an existing draft for the same context rather than creating a second), `save_answer(response, question_id, value)` (validates range, rejects if submitted), `submit(response)` (validates all 25 present, sets status and timestamp in a transaction, enqueues jobs from milestone 5 onward).
- Views: `responses:start` (disclosure page, FR-15, and self-report form, FR-16), `responses:question` (renders question *n*), `responses:save_answer` (HTMX POST, returns the next question fragment), `responses:review` (all answers, submit button), `responses:submit`, `responses:list` (own responses), `responses:detail`.
- Templates: `responses/disclosure.html`, `question.html` (full page) and `_question_fragment.html` (HTMX partial), `review.html`, `list.html`, `detail.html`.
- Root admin: `Response` registered with all fields read-only when `status == submitted`.

**Technical detail**

- `answers` is a JSON object keyed by question id as a string: `{"1": 3, "2": 5}`. Using the database id rather than position means a future reordering of questions does not corrupt old answers.
- Autosave: each question fragment is a form with five radio buttons and `hx-post="{% url 'responses:save_answer' response.id %}" hx-trigger="change" hx-target="#question" hx-swap="innerHTML"`. The view saves and returns the next unanswered question's fragment. Include the CSRF token via `hx-headers` on the body or a `<meta>` tag read by a small inline script.
- Resume: `responses:question` without a number redirects to the first unanswered question, computed from `answers` keys versus the version's question ids.
- Immutability: `save_answer` and `submit` check `status == draft` and return 409 otherwise. The admin makes fields read-only. There is no model-level lock; the service layer is the gate, which is why all writes go through services.
- `submit` validates server-side that every question id in the version has a value within range. The review page shows which are missing and links to them.
- Concurrency: a user with two tabs open can race `save_answer`. Use `select_for_update()` on the response row inside the service so the JSON update is serialised. This is also the pattern `submit` uses.
- The disclosure text names the viewer: "your answers will be visible to you and to <platform name>" for individuals; milestone 3 adds "and to <enterprise name>'s administrators."

**Tests**

- Fixture loads 25 questions, all 1–5, positions 1–25.
- `start_response` twice for the same account and context returns the same draft.
- `save_answer` rejects value 0, 6, a non-integer, an unknown question id, and any write to a submitted response.
- Resume lands on the first unanswered question after answering 1–7 out of order.
- `submit` fails with 24 answers and succeeds with 25; after success, `save_answer` returns 409.
- A user's list shows only their own responses; `detail` for another user's response returns 404.
- Page tests: disclosure, question, review, list and detail render for a verified user; all redirect for an unverified user.

**Done when**

- [ ] On the live site, you can take the survey on a phone, close the browser mid-way, reopen, resume, and submit.
- [ ] Your submitted response appears in your list and detail pages and cannot be edited.
- [ ] Root admin sees the response in the admin, read-only.
- [ ] All tests pass.

**Why this order / what to understand**

This is the first milestone that delivers the product's core, and it does so before enterprises exist. That's deliberate: the survey flow for an individual and for an enterprise member is identical except for one nullable foreign key. Building it once in the simple case and then adding the key is less work than designing both at once.

*Why questions live in the database.* The fixture is just the way v1 gets in. From then on, the code never knows what the questions say; it reads them. Version 2 is a new `SurveyVersion` row plus questions, and old responses still point at version 1, so the detail page renders them correctly forever.

*Why JSON for answers.* The alternative is an `Answer` table with one row per question per response. For 25 numeric answers with no branching, that's 25 rows to write per response and a join to read, for no benefit. JSON keeps the whole response in one row, which also makes the CSV export and the algorithm input trivial. PostgreSQL's JSONB is indexed and queryable if you ever need it.

*Why services, not views.* The `submit` rule ("all 25, in range, status draft, set timestamp, enqueue jobs, all atomic") must be identical whether triggered from the web, a test, or a future admin action. If it lives in a view, it's only available to the view. Putting it in `services.py` makes the view five lines and the rule one place.

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

**Technical detail**

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
- Root admin: a `MatchCandidate` admin list filtered to flagged by default, with actions confirm/reject/unlink, each writing audit rows. Enterprise admin responses table shows the `possible_repeat` flag.
- `submit` now enqueues `run_matching` and `compute_result`; verification now enqueues `run_matching`; invite emails go through `send_email`.

**Technical detail**

- `skip_locked` is what lets two workers run safely later. One worker now; the code already supports more.
- Idempotency: `run_matching` for an account that already has candidates recorded must not duplicate them (the unique pair constraint plus `get_or_create`). `send_email` is the one handler that is not naturally idempotent; accept that a retry after a crash *during* send may double-send, and keep retries conservative.
- Name normalisation for the weak rule: lowercase, strip diacritics, collapse whitespace, compare full name only. Do not attempt fuzzy matching in the MVP.
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
- `apps/accounts/services.delete_account(account, actor, reason)`: in one transaction, collect a summary (counts, enterprise names, response ids), hard-delete responses, results, entitlements on the person if no other accounts, contact points, memberships, the account, and the person if orphaned; then write one `AuditLog` row with the summary. Exposed as an admin action with a confirmation page.
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
- Delete: all expected rows gone, audit row present with the counts; a merged person survives when another account remains.
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
- Privacy text: the disclosure page and a short privacy page naming what is stored and how to request deletion (lawyers to review later; a placeholder is better than nothing).
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

## Milestone map

| # | Milestone | Depends on | Deployable result |
| --- | --- | --- | --- |
| 0 | Foundations and first deploy | — | Empty site on HTTPS with CI/CD |
| 1 | Accounts | 0 | Sign up, verify, log in, reset |
| 2 | Survey and responses | 1 | Individuals take and view the survey |
| 3 | Enterprises, memberships, join | 2 | Enterprise admins onboard members and view responses |
| 4 | Seat pools and entitlements | 3 | Tiers assigned and counted |
| 5 | Jobs, matching, audit | 4 | Worker live; repeats flagged and linked; actions audited |
| 6 | Root admin, export, deletion | 5 | Root console complete; CSV; DPDP deletion |
| 7 | Hardening and pilot | 6 | First customer |

## When to stop and ask

Ask for help (here, or anyone experienced) rather than pushing on when:

- Milestone 0's deploy has eaten more than a couple of days. It's almost always one networking or TLS detail and a second pair of eyes finds it fast.
- A tenant-isolation test is hard to make pass. That's the one place where "I'll fix it later" is not acceptable.
- You're about to write raw SQL, a custom migration operation, or anything with the word "clever" in your head.
- Something works locally and not on the server. The difference is always in configuration; compare `.env` to `.env.example` first.

## Open follow-ups

Things agreed but not done, so they are not forgotten. Move a line to the decision log or delete it when it is finished.

**Waiting on SES production access** (a pending AWS support case; see `04-infrastructure.md`, "Email sending")
- [ ] Live signup by a stranger, verify, log in and out on a phone (Milestone 1, first "Done when" box).
- [ ] Re-test every email flow with a real outside address once approved.

**Business email addresses** (the founder will create more soon)
- [ ] Verify one or two of the new addresses as SES email identities (AWS console, founder's action). While SES is sandboxed they are the only way to receive mail on a second address.
- [ ] Use them to run the live checks for "reset from a second verified email" and "make a second email primary, log in with it, remove the old one", then tick those two Milestone 1 boxes.

**Founder's browser checks still owed for Milestone 1**
- [ ] Live signup with an address SES has not verified: "check your inbox" plus a yellow warning, and the same warning on login. Use `admin@theaccelerare.com` for the live tests, in an incognito window.
- [ ] Signup: submit empty, type in a box, its red error vanishes.
- [ ] Admin: search an account by phone; make-primary and remove on a secondary email; removing a primary shows a red refusal. Then tick "Root admin can find an account by email or phone".
- [ ] Profile page: stored `+number` picks the right flag; "Not now" banner. *(Phone box width and spacing at phone width were checked by headless screenshots in #27; the open flag dropdown was not.)*
- [ ] Live add-email, signup to login, and the reset pages in a real browser.

**Small code and docs follow-ups**
- [ ] A test for the password-reset refused-mail path (it shares `AccountAdapter.send_mail` with signup but has none of its own).
- [ ] Register `/health` with an uptime checker (`04-infrastructure.md`, step 8.4).
- [ ] The README is being written by the founder separately.

## Decision log

| Date | Decision | Reason |
| --- | --- | --- |
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
