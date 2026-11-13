# Backlog — Survey Platform

As of 2026-11-13 · The one list of open tasks and parked decisions · Depends on `05-build-plan.md`

## How to use this document

This is the to-do list that sits beside the build plan. The build plan (`05-build-plan.md`) says what each milestone builds; this file holds everything else that is still open: checks to run, setup to finish, and decisions the founder has parked for later.

- **Part 1** is for people: short, plain, in order of what to look at first.
- **Part 2** is for an AI assistant (or a developer after a long break): the same items with their full context, where they came from, which files they touch, and what to do when each one is resolved.

Every item has an ID (`T-` for tasks, `D-` for decisions, `L-` for later features). The ID is the same in both parts. When an item is finished, delete it from both parts and add a line to the decision log of the doc it belongs to (usually `05-build-plan.md`). Do not keep finished items here. IDs are never reused, so gaps in the numbering are items that were finished.

---

# Part 1 — The short version

## Where things stand (2026-11-13)

Milestones 0, 1 and 2 are built and live, and Milestone 2 was closed on 2026-11-12. Milestone 3 (organizations) was built on 2026-11-12 and 2026-11-13 and is live; what is left of it is your checklist on the live site (T-16). Milestone 4 (licences for organizations) was re-planned with you on 2026-11-13 and is in progress. Payments come straight after it and need planning with you first (T-17). The site is being built for the US first; the India items below are deferred. Every decision below was reviewed with the founder on 2026-11-12; the ones still listed were left here on purpose.

## Waiting on you now

| ID | What | Why it matters |
| --- | --- | --- |
| T-16 | Run the Milestone 3 live checklist (parts A to F in the build plan) | Six of Milestone 3's seven boxes can only be ticked on the live site |
| T-17 | Decide the payments basics: provider and test keys, prices in dollars, refund rule, tax | Payments are the milestone after Milestone 4 and cannot be planned without them |
| T-2 | Set up the uptime checker (Better Stack) once Outlook is back | Nobody is told if the site goes down |
| T-3 | Confirm you did the second-email checks (part F) | Two Milestone 1 boxes can then be ticked |
| T-4 | Check the AWS support case for SES production access | Until it is approved, strangers cannot get a sign-up email |
| T-14 | Pick the inbox that replies to site emails should reach | Then a small PR adds the Reply-To |

## Decisions you have parked

| ID | Question | Needed by | Today's default |
| --- | --- | --- | --- |
| D-2 | If a company asks us to delete all its members' data, what happens? | With D-7, before the pilot | Undecided; ask the privacy lawyer |
| D-4 | Names for the tiers | Any time | Keep "Tier 1/2/3" and "Free" for now (2026-11-12) |
| D-5 | What a free account (no licence) sees on its result page | Milestone 5 | Just the tier name; no results |
| D-6 | How the scoring algorithm and insights stay private | Milestone 5 | Undecided |
| D-7 | The privacy lawyer's list (what is anonymous enough, privacy text, backups, company agreements, consent) | Before the pilot | Not yet asked |
| D-8 | Should people get their own "delete my account" button? | With D-7 | No; staff erase from the admin |
| D-9 | Split Support staff into two groups, and should they read the statements? | When the team grows | One group; they can read the statements |
| D-10 | Show dates in each person's time zone? | If people complain | Day only, in UTC |
| D-11 | Keep `app.theaccelerare.com` or rename it? | Before the pilot, ideally before T-4 and T-10 | `app.` is a placeholder |
| D-15 | Hide whether an email has an account (sign-up timing, reset warning) | If it becomes a concern | Accepted for now (2026-11-12) |
| D-17 | Review the wording that tells a member what an organization's admins can see | With D-7, before the pilot | The wording as built; "fine for now" (2026-11-13) |

## Tasks still open

| ID | What | When |
| --- | --- | --- |
| T-2 | Uptime checker on `/health` (Better Stack) | When Outlook is back |
| T-3 | Part F: password reset from a second email; switch primary email | Confirm it was done |
| T-4 | SES production access, then a real stranger's sign-up and re-testing every email | When AWS approves |
| T-5 | Part E: the Milestone 1 browser checks | Low priority, your call |
| T-6 | Turn on MFA for the `founder` AWS login | Before real customer data |
| T-7 | CloudWatch alarms (CPU, disk, database storage) | Before the pilot |
| T-8 | Test restoring a database backup | Before any real customer |
| T-9 | Upgrade PostgreSQL to a newer major version everywhere | Before the pilot |
| T-10 | Email reputation records (DMARC, own bounce domain) | Before real email volume |
| T-11 | Write the README | Founder, any time |
| T-13 | Silence a harmless VS Code warning in `deploy.yml` | Whenever |
| T-14 | Reply-To on site emails: pick the inbox, then a small PR | When the address is chosen |
| T-16 | Run the Milestone 3 live checklist | Now |
| T-17 | Plan the payments milestone (4b) | After Milestone 4 |

## Later, not yet planned

These are not in any milestone yet. The code is shaped so none of them needs a redesign.

- **L-1** Payments: no longer here. Moved on 2026-11-13 to a milestone straight after Milestone 4 (T-17).
- **L-2** Company single sign-on (SAML or OIDC).
- **L-3** A helper-admin role for enterprises.
- **L-4** Charts and dashboards.
- **L-5** The algorithm, results and insights (Phase 2).
- **L-6** A second version of the survey.
- **L-7** Phone verification by SMS (needs an SMS provider; the Indian sender registration, which takes weeks, is deferred with India).
- **L-8** Moving the servers to Mumbai, with Terraform (deferred with India, 2026-11-13).
- **L-9** Faster pages for UK and India users (CDN or regional move), if latency becomes a problem.
- **L-10** Sending email through Microsoft 365's Graph API instead of SES, if ever wanted.

---

# Part 2 — Detail for AI assistants

Read `CLAUDE.md` and `05-build-plan.md` first. Rules that apply to every item below:

- Do not build anything from a milestone later than the one in progress. As of 2026-11-13 Milestone 3 is code-complete and live, waiting only for the founder's live checklist (T-16). Milestone 4 is in progress: PRs 0 to 5 in `05-build-plan.md`, merged on green without waiting for review, with founder decisions still raised. That arrangement covers Milestone 4 only: ask before using it for payments (Milestone 4b, T-17), which must be planned with the founder before any of it is built. The site is built for the US first (2026-11-13): do not design anything India-specific unless the founder brings it back.
- An item marked **Decision** is the founder's to make. Do not pick an answer. Present the options, recommend one if asked, and wait.
- The founder reviewed every decision on 2026-11-12. Those still here were deliberately left for later; do not re-ask them unprompted unless the milestone that needs them is being planned.
- Never put survey statements, answers or a person's email into this file, a test or an admin history label.
- When an item is resolved: remove it from Part 1 and Part 2, record the outcome in the decision log of the doc it belongs to, and update any doc that mentioned it as open (the "Source" lines say where).
- Steps that need the AWS console, SSH or GitHub are flagged **[console]**. CLAUDE.md asks that every such step be flagged, and that you ask before running anything against AWS.

## Tasks

### T-2 Uptime checker on `/health` (tasklist part G)
- **Status:** open. The founder chose Better Stack Uptime (free plan, commercial use allowed, 3-minute checks) and wants to sign up with an Accelerare address, which is on Microsoft 365. Paused on 2026-11-12 because Outlook was down.
- **Context:** `/health` returns `200` with the body `ok` (`tests/test_health.py`). Sentry cannot report a site that is down, so this is the only "site is down" alarm. The runbook chose "UptimeRobot or similar" at 5 minutes; Better Stack replaces that choice.
- **Steps given to the founder:** sign up; Monitors → Create monitor; "URL becomes unavailable" (or keyword `ok`); URL `https://app.theaccelerare.com/health`; 3 minutes; email alerts (push optional). Suggested adding a personal Gmail as a second recipient so an Outlook outage does not hide an alert. The deliberate "stop the container and see the alert" drill belongs to Milestone 7.
- **When done, update:** `04-infrastructure.md` runbook step 8.4 (remove "Uptime checker not yet registered") and the Resources row "Uptime" (name Better Stack), the "Pending and future" bullet that lists the uptime checker, and add a Better Stack row to NOTES.md's porting checklist (who owns the account, which address gets alerts).
- **Source:** `05-build-plan.md` tasklist part G; `04-infrastructure.md` step 8.4 and "Pending and future".

### T-3 Second-email checks (tasklist part F)
- **Status:** the founder said on 2026-11-12 "I did F, I think". Not confirmed; the boxes stay unticked until they say so.
- **What F is:** verify one or two business addresses as SES email identities **[console]** (the sandbox delivers only to verified addresses), then on the live site: password reset requested from a second verified email (link goes to that address, a link-free notice to the others); make a second email primary, log in with it, remove the old one.
- **When confirmed:** tick Milestone 1 "Done when" boxes 2 ("Password reset works on the live site, from a second verified email too") and 3 ("A user can make a second email primary, log in with it, and remove the old one") in `05-build-plan.md`, with "(founder, live, <date>)".

### T-4 SES production access
- **Status:** requested 2026-10-09 through an AWS support case; last recorded status "awaiting AWS". Not checked since. **[console]**
- **Why it matters:** in the sandbox SES delivers only to verified addresses and at most 200 a day, so a stranger signing up never gets a verification email. Milestone 1 box 1 ("A stranger can sign up on the live site, receive the email, verify, log in and log out on a phone") waits on it.
- **Side effects that end with approval:** the yellow "we could not send the email" warning on signup and login; the reset page's warning that reveals whether an account exists (NOTES.md 2026-10-10 entry; see D-15).
- **When approved:** the founder signs up from an outside address on a phone; re-test every email flow (verify, resend, reset, reset notice, add email). Tick Milestone 1 box 1. Update `04-infrastructure.md` "Email sending" step 7 and the Resources row, and NOTES.md's porting checklist SES row ("a pending support case at the time of writing").
- **If refused or stalled:** the runbook names Postmark, SendGrid or Resend as fallbacks; switching is a settings change through `MAILERS` (Django 6.1), not a code change.

### T-5 Milestone 1 browser checks (tasklist part E)
- **Status:** open; the founder said on 2026-11-12 they are not worried about it. Do not push it.
- **Checks:** live signup with an address SES has not verified shows "check your inbox" plus a yellow warning (and the same on login); signup submitted empty, then typing in a box hides its red error; admin search of an account by phone, make-primary and remove on a secondary email, removing a primary shows a red refusal; profile page picks the right flag for a stored `+number` and the "Not now" banner works (the open flag dropdown has never been looked at in a real browser); live add-email, signup to login, and reset pages in a real browser.
- **Tick when done:** Milestone 1 box 5, "Root admin can find an account by email or phone in the admin".
- **Source:** `05-build-plan.md`, tasklist part E.

### T-6 MFA on the `founder` IAM user
- **Status:** open. Deferred at setup on 2026-10-08. The root user already has MFA. **[console]**
- **Needed by:** before real customer data lands.
- **When done:** update `04-infrastructure.md` (Resources row "AWS account", runbook step 2's "Deviation" note, "Pending and future").

### T-7 CloudWatch alarms
- **Status:** open. **[console]**
- **Planned alarms** (`04-infrastructure.md`, Resources row "Metrics and alarms"): EC2 CPU > 80% for 15 minutes, EC2 status check failed, RDS free storage < 2 GB, RDS CPU > 80%, all to one SNS topic that emails the founder. Disk and memory need the CloudWatch agent (optional for the trial).
- **Needed by:** Milestone 7 at the latest ("Monitors fire when you stop the web container").

### T-8 Backup restore test
- **Status:** never done. **[console]**
- **Steps:** `04-infrastructure.md` runbook section 9 (restore the latest automated snapshot to `survey-restore-test`, point a local Django at it, `showmigrations`, open the admin, delete the instance, write the date in the runbook).
- **Needed by:** before any real customer; a Milestone 7 "Done when" box.

### T-9 PostgreSQL major-version upgrade
- **Status:** open. Decided 2026-10-08 to stay on 16 for now and upgrade local (`docker-compose.yml`), CI (`.github/workflows/ci.yml` service container) and RDS together before the pilot, while the database holds only test data. **[console]** for RDS.
- **First step:** check PostgreSQL 16's end of standard support on RDS and pick the target version. Ask before touching RDS.

### T-10 Email reputation records
- **Status:** open. **[console]** and GoDaddy DNS.
- **What:** a DMARC record for the sending domain (start in monitoring mode, `p=none`) before real volume; optionally a custom MAIL FROM domain so SPF aligns (today DMARC passes on DKIM alone).
- **Source:** `04-infrastructure.md`, "Email sending", future changes. Mind the GoDaddy naming quirk in NOTES.md (the Name field gets the domain appended).

### T-11 README
- **Status:** `README.md` is empty on purpose; the founder is writing it separately. Do not write it unless asked.

### T-13 VS Code warning on `env.IMAGE`
- **Status:** cosmetic. `deploy.yml` sets `IMAGE` at run time through `$GITHUB_ENV`, so the editor flags `env.IMAGE`. Switching to a step output would silence it. Not worth a PR on its own.

### T-14 Reply-To on site emails
- **Status:** decided 2026-11-12 (was D-12): replies to site emails go to a monitored inbox. The address is not chosen yet; candidates offered were a new support address (needs a mailbox or alias in Microsoft 365) or the existing admin address.
- **Build (small PR, once the address exists):** an optional `REPLY_TO_EMAIL` environment variable in `config/settings/production.py` (empty means no header, so local and tests are unchanged); `AccountAdapter.send_mail` in `apps/accounts/` adds `reply_to=[...]` to the message, and the other sends (`services.send_reset_notice` and friends) do the same, ideally through one helper. A test that a sent mail carries the header when the setting is set. Add the variable to `.env.example`, to Parameter Store **[console]** under `/survey/prod/`, and to NOTES.md's porting checklist.
- **Not part of this:** bulk email (consent, unsubscribe, `List-Unsubscribe`, batching through the Milestone 5 queue) stays with the lawyer, D-7.

### T-16 Run the Milestone 3 live checklist
- **Status:** open, waiting on the founder since 2026-11-13. Milestone 3 is code-complete and deployed; six of its seven "Done when" boxes can only be ticked by someone using the live site.
- **What to do:** work through "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 3: parts A to F, one per box (join by code and take the survey; the same by invite; deactivate and reactivate; a second admin; the people limit; erasure). It needs the superuser login, a private window and two spare email addresses, and nothing from SSH, the AWS console or GitHub. While SES is sandboxed (T-4), an address that cannot get mail is marked verified in the Django admin ("Login (allauth)", "Email addresses").
- **Done when:** the founder reports each part. Then a docs-only PR ticks the boxes, records the date in the decision log, updates the status lines (build plan, `CLAUDE.md`, this file) and removes this item. Anything that did not behave as written is fixed first.
- **Source:** `05-build-plan.md`, Milestone 3, "Done when" and "Live checklist".

### T-17 Plan the payments milestone (4b) with the founder
- **Status:** open; it follows Milestone 4. The founder moved payments forward on 2026-11-13 (`05-build-plan.md`, Milestone 4b, and the decision log). Nothing is planned or built.
- **The founder decides first:** the provider (Stripe was suggested for the US, not chosen) and an account with test keys; prices in dollars for Tier 1, 2 and 3, and whether organizations get a volume price; the refund rule (for example, only while the licence is unused); whether sales tax and numbered invoices are needed; whether merging on green applies to this milestone.
- **Then:** a plan in the build plan in the style of Milestones 3 and 4, as that milestone's PR 0. The provider's keys go in Parameter Store **[console]**.
- **Already decided:** see "What is already decided" under Milestone 4b. This replaces L-1.

## Decisions

### D-2 Enterprise-wide deletion requests
- **Status:** undecided; needs the privacy lawyer (D-7). Reviewed 2026-11-12. Milestone 3 was built without it: nothing in the product lets an organization ask for this, so a request would come to staff.
- **Already decided (2026-11-12):** erasing a person **keeps** their membership link; the stripped response stays visible to the enterprise and counts in its historical total. This is the founder's choice, for the lawyer to confirm (recorded in `05-build-plan.md`, Milestone 3 product rules and decision log). Enterprise admins never see answers anyway (decided the same day, settling FR-19's enterprise scope).
- **Still open:** how an enterprise's own request to delete its members' data works (staff erasing each member one by one from the admin is the obvious fallback, but it was not confirmed), and whether the membership link survives that kind of request.
- **Code today:** `apps/accounts/erasure.py`, the strip list is one function, `_anonymise`; `Account.anonymised_at` marks stripped accounts. A completed survey means strip, otherwise hard delete.

### D-4 Tier names
- **Status:** decided for now (2026-11-12): keep "Tier 1", "Tier 2", "Tier 3", and "Free" for tier 0.
- **Where:** `templates/responses/_tier.html`, the one place tier names are rendered. Renaming is a template change plus the tests that assert the words.

### D-5 What tier 0 shows on the result page
- **Status:** reviewed 2026-11-12, left for later. undecided; Milestone 5. The founder suggested sample or limited insights from the paid tiers; alternatives are a limited subset or just an invitation to buy. Today the result page shows date, tier and a results placeholder.
- **Related:** `apps/results/tiering.py` (planned in the Phase 2 stub) maps fields to a minimum tier.

### D-6 Keeping the algorithm and insights private
- **Status:** reviewed 2026-11-12, left for later. undecided; Milestone 5. The repository and the ghcr.io image are public and the founder wants them to stay so.
- **Options recorded:** a second private repository installed as a package (makes the image private, so the server needs `docker login ghcr.io` with a `read:packages` token; NOTES.md 2026-10-07 entry on ghcr visibility), or a file loaded at run time, the way the survey wording is loaded through the admin (Milestone 2 PR 9).

### D-7 The privacy lawyer's list
- **Status:** reviewed 2026-11-12, left for later. not yet asked. Needed before the pilot (Milestone 7).
- **Questions collected so far:** is "strip email, phone and name, keep results and demographics" anonymous enough in the US, UK and India (age, gender, company and exact dates can identify someone in a small company); what the privacy text and disclosure page must say (the wording now on the site is listed under D-17); how long erased data may stay in RDS backups (30 days today); enterprise data agreements; D-2 and the founder's "keep the membership link on erasure" choice; consent and verifiable parental consent for under-18s in India (minors do not take the survey); transfers to the US, a UK representative and ICO registration; India's DPDP Act (substantive duties from 2027-05-13); consent, an unsubscribe link and `List-Unsubscribe` for bulk email (for example a feedback request to everyone who took the survey), which would be sent in batches through the Milestone 5 queue; data minimisation (an age band, optional gender) before demographics are collected; an invite sent to someone who never made an account keeps their address on the invite row, and the erase page works on accounts, so there is no admin tool yet to remove it.
- **Source:** `05-build-plan.md` open follow-ups and Milestone 7; `04-infrastructure.md` "Pending and future".

### D-8 A user-facing "delete my account" button
- **Status:** reviewed 2026-11-12, left for later. not built; staff erase from the admin (superuser-only button with a typed email and a reason). Decide with D-7, including the wording.

### D-9 Splitting Support staff
- **Status:** reviewed 2026-11-12, left for later. later, when needed. Today one "Support staff" group serves debugging and business insight. Its permissions are two named lists in `apps/responses/signals.py` (a `post_migrate` receiver, not a migration; see NOTES.md). The founder is fine with them reading the statements for now through the read-only Questions and Survey versions pages (decision 2026-10-10). Decide then whether either group may read them.

### D-10 Dates and time zones
- **Status:** reviewed 2026-11-12, left for later. accepted for now. History and result pages show the day only, in UTC, so they can be a day off far from UTC. Fixing it needs a time zone per account, which is not collected. Revisit if people are confused.

### D-11 The site's real address
- **Status:** reviewed 2026-11-12, left for later. `app.theaccelerare.com` is a working name; rename before the pilot. **[console]** and GoDaddy.
- **A rename touches:** the GoDaddy A record, `ALLOWED_HOSTS` in Parameter Store, `deploy/Caddyfile`, the SES domain identity and its three DKIM records (SES is verified for `app.theaccelerare.com`; a new sending domain needs re-verification and possibly a new production-access check), `DEFAULT_FROM_EMAIL`, and the docs and NOTES that name it. Decide before T-10 so the DMARC work is not done twice.

### D-15 Revealing whether an email has an account
- **Status:** accepted for now (confirmed 2026-11-12). Two leaks: sign-up answers "check your inbox" either way, but a real send takes longer (NOTES.md 2026-10-09); and while SES is sandboxed the reset page warns "could not send" only for addresses that have an account (NOTES.md 2026-10-10). The second fades with T-4. Revisit if account enumeration ever matters.

### D-17 The wording that tells a member what an organization can see
- **Status:** the founder read both texts on 2026-11-13 and accepted them as they are ("fine for now"), asking for a later review. Nothing is waiting on this. Review it with the privacy lawyer's list (D-7), before the pilot.
- **Where the words are:** the join confirmation page, shown before someone joins an organization (`templates/enterprises/join_confirm.html`, Milestone 3 PR 10), and the organization version of the survey's "Before you begin" page (`templates/responses/disclosure.html`, PR 7). Both list what the organization's admins can see and what they never see. The code keeps those promises: `tests/test_tenant_isolation.py` holds the admin pages to them.
- **The five lines that were a judgment call:**
  1. "your results for that survey, once results are available": this promises members that their organization's admins will see their results in Phase 2. It is the largest promise on the page.
  2. "a mark if it looks as though you have taken the survey before": this tells members the repeat check exists. The alternative is to tell admins only.
  3. "Accelerare keeps your answers to produce your results and to improve the diagnostic" (disclosure page only): a statement of how Accelerare uses the data; the line a lawyer most needs to read.
  4. "results level" and "its level" stand in for the tier names, which are still placeholders (D-4).
  5. The join page says nothing about Accelerare itself seeing the answers; only the survey's page does.
- **When the wording changes:** the four "admins can also see" survey lines must stay the same on both pages (the join page says "that survey" where the other says "this survey"); `tests/test_join_pages.py` compares the two files and fails if they drift. `tests/test_survey_context_pages.py` and `tests/test_join_pages.py` also quote the wording.
- **Source:** raised with the founder on 2026-11-13 after Milestone 3 PRs 7 and 10.

### Small things to revisit only if they come up
- **Spelling:** the site says "licence" (British) and "organization" (US, the founder's choice on 2026-11-12). Pick one spelling for the whole site if anyone notices.
- SES **Mail Manager** (managed credential rotation) was not chosen; revisit if rotating the SMTP credential by hand becomes a chore.
- **allauth** was chosen for verification and later SSO; revisit if it fights the Milestone 3 join flows (`03-tech-stack.md` decision log).
- **Erasing and revoking at the same moment:** erasing an account and revoking one of its licences lock rows in opposite orders, so if staff did both in the same instant PostgreSQL would stop one with a deadlock error and it would have to be repeated (NOTES.md 2026-11-12). Nothing is lost. Fix the lock order if it is ever seen.
- **No favicon:** every page logs a 404 for `/favicon.ico`. Cosmetic; add an icon when there is a logo.
- **The licence form's tier box:** in the Django admin the tier is typed as a number (1 to 3) rather than picked from a list. Make it a dropdown if staff ever mistype it.
- **After "this invite was sent to another address":** the person is told to add and verify that address on their profile and open the link again; they are not brought back to the invite automatically.
- **Possible repeats:** organization admins have a "possible repeat" filter and mark, but nothing sets `Response.possible_repeat` until matching exists (Milestone 5).
- **Known refused edge:** account A has verified `x@`, but account B registered with `x@` and never verified it, so `x@` is B's login name and A's make-primary is refused (NOTES.md 2026-10-09).

## Later features

None of these is in a milestone. Each has a seam in the current design (`02-architecture.md`, "Deferred extension points"); building one is a new plan, not a redesign.

- **L-1 Payments.** Moved on 2026-11-13 to Milestone 4b, straight after Milestone 4; see T-17. What follows is the earlier note, kept for what it decided ("Likely Razorpay for India" is deferred with India). Writes licences through the same services the admin uses (`grant_individual` with source `purchase`, the seat-pool services). Already decided: licences do not expire, a retake needs another licence, upgrades happen in place. Needs a payment ledger (amount, currency, date, invoice number, provider reference, licence id and tier) with no personal identity, so an erasure never removes an accounting record; refunds revoke through the service; the funnel records `licence_granted` with source `purchase`; reminders for unused licences once the worker exists. See `05-build-plan.md`, "Phase 3 stub".
- **L-2 SSO per enterprise** (SAML or OIDC), optional beside local accounts. FR-5. A second login method on the account; memberships unchanged.
- **L-3 Helper admin.** Requirements undefined. A third value in `membership.role` or a platform role table.
- **L-4 Dashboards and charts.** FR-21. Read-only queries over responses and results.
- **L-5 Algorithm, results and insights (Phase 2).** The seam is planned for Milestone 5: `apps/results/` with `compute_result` returning `None`, `visible_fields` and `recompute_results`. See `05-build-plan.md`, "Phase 2 stub", and D-5, D-6.
- **L-6 Survey version 2.** New `SurveyVersion` and `Question` rows; old responses keep their version.
- **L-7 Phone verification by SMS.** Needs a paid SMS provider and per-country sender registration (India DLT takes weeks). Turning it on activates the verified-phone matching rule, which is inert until then.
- **L-8 Move to Mumbai (Phase 4).** `04-infrastructure.md`, "Moving to Mumbai"; SES must be set up and out of the sandbox in `ap-south-1` first; write Terraform at that point.
- **L-9 Latency for UK and India.** About 150 ms from the UK and 250 ms from India to Oregon. A CDN or the regional move if it becomes a real problem; one database in one region, with replicas if it grows.
- **L-10 Email through Microsoft Graph.** No redesign: a small backend class behind `MAILERS["default"]["BACKEND"]` plus an Entra app limited to one mailbox. Only if SES is ever unsuitable.
