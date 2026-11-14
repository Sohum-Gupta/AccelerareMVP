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

Milestones 0, 1 and 2 are built and live, and Milestone 2 was closed on 2026-11-12. Milestone 3 (organizations) was built on 2026-11-12 and 2026-11-13 and is live; what is left of it is your checklist on the live site (T-16). Milestone 4 (licences for organizations) was built on 2026-11-13 and is live; what is left of it is your checklist on the live site (T-18). Nobody has yet tried Milestone 3 or Milestone 4 by hand on the live site. On 2026-11-13 you answered the choices made while building Milestone 4, the payments basics, and the two GitHub questions; the answers are in the build plan's decision log. What follows from them is built in this order: the licence changes (a licence is set aside when an invite or code promises one; built and live the same day, with two live checks added to T-18), then payments (Milestone 4b; built and deployed the same day; your Stripe test keys reached the server that afternoon, so buying is open on test keys and is yours to try, T-22), then Milestone 5 (background jobs, the licence email, the audit log, possible duplicates; built and deployed the same day, with a live checklist that is yours to run, T-24). Nobody has yet tried Milestone 5 by hand on the live site either. The same day you set up the uptime checker (Better Stack), confirmed Sentry is on its free plan, set up Stripe's test keys, and asked AWS again for SES production access after finding the October request had been refused. That afternoon the interface points you had raised on the live site were all built (the last page's button submits; a "Show password" button; a tidy account page; "My surveys" after login; two fixes in the Django admin), with a button to look for duplicates among existing accounts. Milestone 6, which you asked to have planned and built like Milestone 5, was planned and built that evening (an organization's admins and staff can download surveys as a spreadsheet file, each download is recorded, an erasure records what it removed, the Django admin's first page shows the numbers that matter, and there is a written procedure for deletion requests); it is live, and what is left of it is your checklist (T-27). Nobody has yet tried Milestone 6 by hand on the live site. Milestone 7 (hardening and the pilot) followed the same evening, at your word: calm error pages, a privacy page, a limit on guessing join codes, account numbers on error reports, a load check, and a button to send a test error to Sentry. It is live. What is left of it is yours: a short live checklist (T-28) and the things only you can do before a first customer, gathered in `09-pilot-checklist.md`. **Nothing is in progress: every milestone of Phase 1 is built. Phase 2 (the algorithm) has not been asked for.** The site is being built for the US first; the India items below are deferred. Every decision below was reviewed with the founder on 2026-11-12; the ones still listed were left here on purpose.

## Waiting on you now

| ID | What | Why it matters |
| --- | --- | --- |
| T-16 | Run the Milestone 3 live checklist (parts A to F in the build plan) | Six of Milestone 3's seven boxes can only be ticked on the live site |
| T-18 | Run the Milestone 4 live checklist (parts A to D in the build plan, and parts E and F for its second part) | Four of Milestone 4's five boxes, and two of its second part's three, can only be ticked on the live site |
| T-22 | Run the Milestone 4b live checklist with Stripe's test card (parts A to C in the build plan). The keys are on the server, so it can be run now | Nothing has been run against Stripe itself yet; three of its four boxes can only be ticked on the live site |
| T-24 | Run the Milestone 5 live checklist (parts A to D in the build plan, and E if you like) | Four of Milestone 5's five boxes can only be ticked on the live site; the worker has never sent a real email |
| T-28 | Run the Milestone 7 live checklist (parts A to C in the build plan), then work through `09-pilot-checklist.md` | Part B is the only way to know that errors reach Sentry; the privacy page went live unread |
| T-27 | Run the Milestone 6 live checklist (parts A to D in the build plan, and E if you like), and read `08-deletion-requests.md` | Four of Milestone 6's five boxes can only be ticked on the live site; no file has been opened in a spreadsheet by a person |
| T-3 | Confirm you did the second-email checks (part F) | Two Milestone 1 boxes can then be ticked |
| T-4 | Check the new AWS case for SES production access from 2026-11-14 (the October request was refused; you asked again on 2026-11-13) | Until it is approved, strangers cannot get a sign-up email |
| T-14 | Pick the inbox that replies to site emails should reach | Then a small PR adds the Reply-To |

## Decisions you have parked

| ID | Question | Needed by | Today's default |
| --- | --- | --- | --- |
| D-2 | If a company asks us to delete all its members' data, what happens? | With D-7, before the pilot | Undecided; ask the privacy lawyer |
| D-4 | Names for the tiers | Any time | Keep "Tier 1/2/3" and "Free" for now (2026-11-12) |
| D-6 | How the scoring algorithm and insights stay private | When the algorithm is built (Phase 2) | Undecided |
| D-7 | The privacy lawyer's list (what is anonymous enough, privacy text, backups, company agreements, consent) | Before the pilot | Not yet asked |
| D-8 | Should people get their own "delete my account" button? | With D-7 | No; staff erase from the admin |
| D-9 | Split Support staff into two groups, and should they read the statements? | When the team grows | One group; they can read the statements |
| D-10 | Show dates in each person's time zone? | If people complain | Day only, in UTC |
| D-11 | Keep `app.theaccelerare.com` or rename it? | Before the pilot, ideally before T-4 and T-10 | `app.` is a placeholder |
| D-15 | Hide whether an email has an account (sign-up timing, reset warning) | If it becomes a concern | Accepted for now (2026-11-12) |
| D-20 | Review sales tax and invoices with an accountant, and with it whether to use Stripe's "Managed Payments" (Stripe handles tax, fraud and disputes for 3.5% more) | Before real prices are set | No tax collected; Stripe's receipt, and a numbered invoice for an organization; Managed Payments not used |
| D-17 | Review the wording that tells a member what an organization's admins can see | With D-7, before the pilot | The wording as built; "fine for now" (2026-11-13) |

## Tasks still open

| ID | What | When |
| --- | --- | --- |
| T-3 | Part F: password reset from a second email; switch primary email | Confirm it was done |
| T-4 | SES production access (asked again 2026-11-13), then a real stranger's sign-up and re-testing every email | Check the case from 2026-11-14 |
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
| T-18 | Run the Milestone 4 live checklist | Now |
| T-23 | Record bounces and complaints from Amazon SES and stop writing to those addresses | Before real email volume; needs the AWS console |
| T-22 | Run the Milestone 4b live checklist | Now |
| T-24 | Run the Milestone 5 live checklist | Now; part B needs an address Amazon SES can deliver to |
| T-26 | Uptime checker, four small things: watch the worker too, avoid false alarms during a deploy, a second place for alerts, and the free plan's terms | When you next open Better Stack |
| T-27 | Run the Milestone 6 live checklist | Now |
| T-28 | Run the Milestone 7 live checklist, then the pilot checklist | Now; part B raises a Sentry alert on purpose |
| T-29 | Decide whether to close the SSH port | Before the pilot, on a quiet day |

## Later, not yet planned

These are not in any milestone yet. The code is shaped so none of them needs a redesign.

- **L-1** Payments: no longer here. Moved on 2026-11-13 to a milestone straight after Milestone 4 (Milestone 4b in the build plan).
- **L-2** Company single sign-on (SAML or OIDC).
- **L-3** A helper-admin role for enterprises.
- **L-4** Charts and dashboards.
- **L-5** The algorithm, results and insights (Phase 2).
- **L-6** A second version of the survey.
- **L-7** Phone verification by SMS (needs an SMS provider; the Indian sender registration, which takes weeks, is deferred with India).
- **L-8** Moving the servers to Mumbai, with Terraform (deferred with India, 2026-11-13).
- **L-9** Faster pages for UK and India users (CDN or regional move), if latency becomes a problem.
- **L-10** Sending email through Microsoft 365's Graph API instead of SES, if ever wanted.
- **L-11** Linking a third login to one person (today a person has two linked logins at most).
- **L-12** A faster same-name check for possible duplicates, once there are many thousands of members.

---

# Part 2 — Detail for AI assistants

Read `CLAUDE.md` and `05-build-plan.md` first. Rules that apply to every item below:

- Do not build anything from a milestone later than the one in progress. As of 2026-11-13 Milestones 3 and 4 are both code-complete and live, each waiting only for the founder's live checklist (T-16, T-18). The work in progress is what the founder asked for on 2026-11-13, in this order: the licence changes that follow from their answers on Milestone 4's choices (built and live; "Milestone 4, second part" in the build plan), payments (Milestone 4b; code-complete and deployed, open on the live site on Stripe's test keys since 2026-11-13, with the live checklist T-22), then Milestone 5 (code-complete and deployed; the live checklist is T-24). All three are built. Milestone 6 was then planned (as its PR 0) and built the same way, at the founder's word, and is code-complete and deployed (the live checklist is T-27). Milestone 7 (hardening and the pilot) was then planned and built the same way and is code-complete and deployed (T-28). **Nothing is in progress: Phase 1 is built. Phase 2 (the algorithm, L-5) has not been asked for, so do not start it.** Merging on green without review ended with Milestone 7; ask before doing it for anything further. `main` is protected: every change goes through a pull request whose `test` check has passed. The site is built for the US first (2026-11-13): do not design anything India-specific unless the founder brings it back.
- An item marked **Decision** is the founder's to make. Do not pick an answer. Present the options, recommend one if asked, and wait.
- The founder reviewed every decision on 2026-11-12. Those still here were deliberately left for later; do not re-ask them unprompted unless the milestone that needs them is being planned.
- Never put survey statements, answers or a person's email into this file, a test or an admin history label.
- When an item is resolved: remove it from Part 1 and Part 2, record the outcome in the decision log of the doc it belongs to, and update any doc that mentioned it as open (the "Source" lines say where).
- Steps that need the AWS console, SSH or GitHub are flagged **[console]**. CLAUDE.md asks that every such step be flagged, and that you ask before running anything against AWS.

## Tasks

### T-3 Second-email checks (tasklist part F)
- **Status:** the founder said on 2026-11-12 "I did F, I think". Not confirmed; the boxes stay unticked until they say so.
- **What F is:** verify one or two business addresses as SES email identities **[console]** (the sandbox delivers only to verified addresses), then on the live site: password reset requested from a second verified email (link goes to that address, a link-free notice to the others); make a second email primary, log in with it, remove the old one.
- **When confirmed:** tick Milestone 1 "Done when" boxes 2 ("Password reset works on the live site, from a second verified email too") and 3 ("A user can make a second email primary, log in with it, and remove the old one") in `05-build-plan.md`, with "(founder, live, <date>)".

### T-4 SES production access
- **Status:** asked for a second time on 2026-11-13; awaiting AWS. **[console]** The first request (2026-10-09) was **refused on 2026-10-10**, with no reason given, and AWS closed the case. Nobody looked at it again until 2026-11-13, so these docs said "awaiting AWS" for five weeks while the answer was no. On 2026-11-13 the SES dashboard still said sandbox in US West (Oregon), 200 emails a day. The founder made a new request from the SES dashboard and answered AWS's six questions on the new case the same day.
- **What the founder told AWS (as reported to Claude):** the application's address and the company's main site; transactional mail only (sign-up confirmation, password reset and its notice, organization invites, and notices such as a licence being given); fewer than 100 emails a day; no mailing list and no bought or imported addresses; the account-level suppression list is enabled for bounces and complaints; recording of bounces and complaints through SNS is "being added" (that is T-23, which is not built); Easy DKIM on the verified domain.
- **Suppression list:** the founder confirmed on 2026-11-13 that the account-level suppression list is switched on (SES, Configuration, Suppression list, Account-level settings), as the answer to AWS says.
- **Next:** look at the case from 2026-11-14. AWS's reply goes to the AWS account's email and shows in the Support Center.
- **Why it matters:** in the sandbox SES delivers only to verified addresses and at most 200 a day, so a stranger signing up never gets a verification email. Milestone 1 box 1 ("A stranger can sign up on the live site, receive the email, verify, log in and log out on a phone") waits on it. So does anyone receiving the licence email (Milestone 5) at an address SES has not verified.
- **Side effects that end with approval:** the yellow "we could not send the email" warning on signup and login; the reset page's warning that reveals whether an account exists (NOTES.md 2026-10-10 entry; see D-15).
- **When approved:** the founder signs up from an outside address on a phone; re-test every email flow (verify, resend, reset, reset notice, add email, invite, licence given). Tick Milestone 1 box 1. Update `04-infrastructure.md` "Email sending" step 7 and the Resources row, and NOTES.md's porting checklist SES row.
- **If refused again:** do not ask a third time without changing something. The runbook names Postmark, SendGrid or Resend as fallbacks; switching is a settings change through `MAILERS` (Django 6.1), not a code change. T-23 being built first (so the answer about bounces is "done", not "being added") is the other thing that could change AWS's answer.

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
- **Status:** decided 2026-11-12 (was D-12): replies to site emails go to a monitored inbox. Raised again on 2026-11-13; the founder said to leave it for now. The address is not chosen yet; candidates offered were a new support address (needs a mailbox or alias in Microsoft 365) or the existing admin address.
- **Build (small PR, once the address exists):** an optional `REPLY_TO_EMAIL` environment variable in `config/settings/production.py` (empty means no header, so local and tests are unchanged); `AccountAdapter.send_mail` in `apps/accounts/` adds `reply_to=[...]` to the message, and the other sends (`services.send_reset_notice` and friends) do the same, ideally through one helper. A test that a sent mail carries the header when the setting is set. Add the variable to `.env.example`, to Parameter Store **[console]** under `/survey/prod/`, and to NOTES.md's porting checklist.
- **The privacy page waits for the same address (Milestone 7).** `/privacy/` prints no address for deletion requests while `CONTACT_EMAIL` is empty; it says who to ask instead. When the inbox is chosen, add `CONTACT_EMAIL` to Parameter Store **[console]** under `/survey/prod/` and deploy: the page then prints it, with no code change. Use the same inbox for the Reply-To.
- **Not part of this:** bulk email (consent, unsubscribe, `List-Unsubscribe`, batching through the Milestone 5 queue) stays with the lawyer, D-7.

### T-16 Run the Milestone 3 live checklist
- **Status:** open, waiting on the founder since 2026-11-13. Milestone 3 is code-complete and deployed; six of its seven "Done when" boxes can only be ticked by someone using the live site.
- **What to do:** work through "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 3: parts A to F, one per box (join by code and take the survey; the same by invite; deactivate and reactivate; a second admin; the people limit; erasure). It needs the superuser login, a private window and two spare email addresses, and nothing from SSH, the AWS console or GitHub. While SES is sandboxed (T-4), an address that cannot get mail is marked verified in the Django admin ("Login (allauth)", "Email addresses").
- **Done when:** the founder reports each part. Then a docs-only PR ticks the boxes, records the date in the decision log, updates the status lines (build plan, `CLAUDE.md`, this file) and removes this item. Anything that did not behave as written is fixed first.
- **Source:** `05-build-plan.md`, Milestone 3, "Done when" and "Live checklist".

### T-18 Run the Milestone 4 live checklist
- **Status:** open, waiting on the founder since 2026-11-13. Milestone 4 is code-complete and deployed; four of its five "Done when" boxes can only be ticked by someone using the live site. Nothing of Milestone 4 has been tried by a person there yet: the "Licence stock" page of the Django admin, the Licences page and the tier drop-downs have only been exercised by tests and by browser runs against a local server.
- **What to do:** work through "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 4: parts A to D, one per box (staff set the stock, the admin gives a licence and the member takes the survey; change a tier and take a licence back; a join code that carries a tier; the people limit). It needs the superuser login, a private window and three accounts with verified email addresses, and nothing from SSH, the AWS console or GitHub. It is written for a new organization, so the numbers on the screen match the ones in the checklist. It can be run before or after T-16; accounts from one serve the other unless they were erased.
- **Since 2026-11-13 it has two more parts.** The second part of Milestone 4 (licences set aside for invites and codes; emailing an invite again and moving it) added parts E and F, under "Milestone 4, second part" in the build plan. Part C of the first checklist was rewritten the same day, because a join code with a licence can now be made only while the stock covers it. Parts E and F want two more accounts with verified addresses.
- **Done when:** the founder reports each part. Then a docs-only PR ticks the boxes, records the date in the decision log, updates the status lines (build plan, `CLAUDE.md`, this file) and removes this item. Anything that did not behave as written is fixed first.
- **Source:** `05-build-plan.md`, Milestone 4 and "Milestone 4, second part", "Done when" and "Live checklist".

### T-22 Run the Milestone 4b live checklist
- **Status:** open, waiting on the founder, since 2026-11-13. The founder did the Stripe steps that day (a sandbox account, the test secret key and the webhook's signing secret in Parameter Store, receipts switched on; this was task T-21, now removed). The secrets have reached the server: at 2:09pm PST an unsigned request to the webhook was answered "Bad signature", where at 12:22pm it had been answered "Not set up". Whether the buy page has stopped saying "Buying online is not open yet" is step 1 of part A; nobody has looked. Milestone 4b is code-complete and deployed. **Nothing in it has been run against Stripe:** every test uses a stand-in. The first real payment page, the first real message from Stripe and the first real refund will be the founder's, on test keys.
- **What to do:** "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 4b: part A (a person buys a licence and upgrades it), part B (an organization buys three), part C (a refund from the Django admin, and one that is refused). Stripe's test card is `4242 4242 4242 4242`. It needs the superuser login, a second ordinary account, an organization, and Stripe's dashboard in test mode.
- **If something fails:** note what the page said and when. Sentry will have the error, without the person's details. The file that talks to Stripe is `apps/payments/stripe_api.py`; a payment that arrived but could not be finished is marked "needs attention" under "Payments" in the Django admin, with the reason.
- **Done when:** the founder reports each part. Then a docs-only PR ticks the three boxes, records the date in the decision log, updates the status lines and removes this item.
- **Source:** `05-build-plan.md`, Milestone 4b, "Done when" and "Live checklist".

### T-24 Run the Milestone 5 live checklist
- **Status:** open, waiting on the founder, since 2026-11-13. Milestone 5 is code-complete and deployed (PRs 0 to 7, #84 to #91). The server runs a third container, the worker. **Nothing in it has been tried by a person on the live site, and the worker has never sent a real email.**
- **What to do:** "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 5: part A (a test job shows as done), part B (give a licence, the member gets the email), part C (two accounts with one phone number become a possible duplicate; link them, see the licence shared, undo it), part D (the audit log shows all of it by account number), and the optional part E (the box under "Yes"). It needs the superuser login, an organization with a licence in its stock, a member whose address Amazon SES can deliver to, and a second ordinary account. Nothing needs SSH, GitHub or the AWS console.
- **If something fails:** note what the page said and when. Django admin, "Background jobs", shows a job that failed and the kind of error; Sentry has the rest, without anyone's details. If the email in part B does not come and the job's error is "SMTPRecipientsRefused", that is Amazon SES's sandbox refusing the address (T-4), not the site. If "Background jobs" says jobs have been waiting a long time, the worker is not running: `/health/worker` then says "behind", and the last Deploy run on GitHub will show why.
- **Done when:** the founder reports each part. Then a docs-only PR ticks the four boxes, records the date in the decision log, updates the status lines and removes this item.
- **Source:** `05-build-plan.md`, Milestone 5, "Done when" and "Live checklist".

### T-28 Run the Milestone 7 live checklist, then the pilot checklist
- **Status:** open, waiting on the founder, since 2026-11-13. Milestone 7 is code-complete and deployed (PRs 0 to 7, #107 to #113 and the closing docs PR). **Nothing in it has been tried by a person on the live site. No error report has been seen in Sentry. The privacy page is live and no lawyer has read it.**
- **What to do first:** "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 7: part A (a wrong address shows "Page not found"), part B ("Send a test error…" on the Background jobs page, then look in Sentry for two `DeliberateError` reports), part C (read `/privacy/`), and the optional part D (eleven wrong join codes). **Part B raises a Sentry alert on purpose.**
- **Then:** `09-pilot-checklist.md`. Its Part 1 is the table of what must be done before a real customer's data (T-4, T-6, T-7, T-8, T-14, T-26, T-29, D-7, D-11, D-20); Part 3 is the drill that stops the web container **[SSH]**, which takes the site down for a few minutes; Part 4 is how to bring on the first organization from the Django admin.
- **If something fails:** if no error arrives in Sentry, `SENTRY_DSN` in Parameter Store is empty or wrong (`04-infrastructure.md`). If only the worker's is missing, the worker's log line is not being picked up as an error: tell Claude.
- **Done when:** the founder reports parts A to C; a docs-only PR then ticks boxes 1 and 4 of Milestone 7. Boxes 2, 3 and 5 are ticked as the pilot checklist is worked through.
- **Source:** `05-build-plan.md`, Milestone 7; `09-pilot-checklist.md`.

### T-29 The SSH port
- **Status:** open; decided on 2026-11-12 to revisit in Milestone 7, and on 2026-11-13 left as it is for now. **[console]**
- **Today:** port 22 on the server is open to anywhere, with key-only login. The deploy reaches the server over SSH.
- **The choice:** leave it (accepted for the trial); restrict the port to known addresses (GitHub's deploy runners do not have a fixed one, so this needs a different way to deploy); or close it and use AWS Session Manager for both people and the deploy.
- **Why not tonight:** any of these changes how every deploy reaches the server. A mistake stops deploys, or locks everyone out. Do it on a quiet day, with the founder at the AWS console.
- **Needed by:** before the pilot, as a decision; the change itself can follow.

### T-27 Run the Milestone 6 live checklist
- **Status:** open, waiting on the founder, since 2026-11-13. Milestone 6 is code-complete and deployed (PRs 0 to 6, #100 to #105 and the closing docs PR). **Nothing in it has been tried by a person on the live site, and no downloaded file has been opened in a spreadsheet program by a person** (the tests read the files with Python's `csv` module).
- **What to do:** "Live checklist (for the founder)" in `05-build-plan.md`, Milestone 6: part A (an organization's admin downloads the file and opens it), part B (the two staff files; Support staff get only the one without answers), part C (erase a test account and find the numbers in the audit log), part D (the numbers on the Django admin's first page, each opening its list), and the optional part E (links, "Related" lines and search). It needs the superuser login, an organization with at least one submitted survey, and a test account to erase. Nothing needs SSH, GitHub or the AWS console.
- **Also:** read `08-deletion-requests.md`. The 30 days are decided (founder, 2026-11-13: an account is erased within 30 days of the request, and the person can withdraw until then). Who may ask is still the builder's draft, for the founder and the privacy lawyer to settle (D-7).
- **If something fails:** note what the page said and when. A download that fails halfway is still in the audit log (`responses.exported` is written before the first line is sent). If a file opens with every row in one column, the spreadsheet program was told the wrong separator: the file is comma-separated.
- **Done when:** the founder reports each part. Then a docs-only PR ticks the four boxes, records the date in the decision log, updates the status lines and removes this item.
- **Source:** `05-build-plan.md`, Milestone 6, "Done when" and "Live checklist".

### T-26 Uptime checker: four small follow-ups
- **Status:** open, the founder's, since 2026-11-13. **[console]** (Better Stack's site; nothing in AWS.) The uptime checker itself is done: a Better Stack account on the free plan under the founder's Accelerare address, one monitor on `https://app.theaccelerare.com/health` every 3 minutes, email alerts, and a test alert that arrived (this was task T-2, now removed).
- **1. Watch the worker too.** The founder agreed to this on 2026-11-13; it is theirs to add. Add a second monitor on `https://app.theaccelerare.com/health/worker`, "URL becomes unavailable". That address answers "ok", or "behind" with status 503 when a background job has waited more than ten minutes, which means the worker has stopped. Without it nobody is told if the worker dies; the site carries on and emails quietly stop.
- **2. False alarms during a deploy.** The monitor's confirmation period is "Immediate start", so a check that lands in the few seconds a deploy restarts the site could raise an alarm. Setting it to 1 minute fixes that. Do the same on the worker's monitor.
- **3. One address gets the alerts.** The second recipient T-2 suggested (a personal address, so an Outlook outage cannot hide an alert) needs a paid Responder seat, and the founder skipped it and the free phone push notification. Alerts therefore go to one Microsoft 365 address only. The free push notification in Better Stack's phone app is the cheapest second channel.
- **4. The free plan's terms.** The pricing page calls the tier "Free for personal projects", while the choice of Better Stack was recorded as "commercial use allowed". Nobody has read the terms. Read them, or accept the small risk; UptimeRobot is the fallback the runbook first named.
- **The drill** (stop the container, see the alert arrive) belongs to Milestone 7, as before.
- **Source:** the founder's setup session of 2026-11-13; `04-infrastructure.md`, the Resources row "Uptime".

### T-23 Bounces and complaints from Amazon SES
- **Status:** open; moved out of Milestone 5 on 2026-11-13 (the founder accepted this as a default before the re-plan). Decided on 2026-11-12 that the site should record them and stop sending to an address that hard-bounced or complained.
- **Why it is not in the build:** SES reports these through an SNS topic that has to be made, subscribed and confirmed in the AWS console **[console]**, and the address it calls must be public. That is the founder's console work first, and there is no AWS access on the build machine.
- **Until then:** SES's own account-level suppression list stops repeat sends to an address that bounced, and a weekly look at the SES reputation page covers the rest (`04-infrastructure.md`, "Email sending").
- **When built:** a small receiver for SNS's message (its signature checked, like Stripe's), a table of addresses not to write to, a check before every send, and the list visible to staff in the Django admin. The Milestone 5 worker can do the sending check.
- **Needed by:** before real email volume; with T-4 (SES production access) and T-10 (DMARC).

## Decisions

### D-2 Enterprise-wide deletion requests
- **Status:** undecided; needs the privacy lawyer (D-7). Reviewed 2026-11-12. Milestone 3 was built without it: nothing in the product lets an organization ask for this, so a request would come to staff.
- **Already decided (2026-11-12):** erasing a person **keeps** their membership link; the stripped response stays visible to the enterprise and counts in its historical total. This is the founder's choice, for the lawyer to confirm (recorded in `05-build-plan.md`, Milestone 3 product rules and decision log). Enterprise admins never see answers anyway (decided the same day, settling FR-19's enterprise scope).
- **Still open:** how an enterprise's own request to delete its members' data works (staff erasing each member one by one from the admin is the obvious fallback, but it was not confirmed), and whether the membership link survives that kind of request.
- **Code today:** `apps/accounts/erasure.py`, the strip list is one function, `_anonymise`; `Account.anonymised_at` marks stripped accounts. A completed survey means strip, otherwise hard delete.

### D-4 Tier names
- **Status:** decided for now (2026-11-12): keep "Tier 1", "Tier 2", "Tier 3", and "Free" for tier 0.
- **Where:** `templates/responses/_tier.html`, the one place tier names are rendered. Renaming is a template change plus the tests that assert the words.

### D-6 Keeping the algorithm and insights private
- **Status:** reviewed 2026-11-12, left for later. undecided; Milestone 5. The repository and the ghcr.io image are public and the founder wants them to stay so.
- **Options recorded:** a second private repository installed as a package (makes the image private, so the server needs `docker login ghcr.io` with a `read:packages` token; NOTES.md 2026-10-07 entry on ghcr visibility), or a file loaded at run time, the way the survey wording is loaded through the admin (Milestone 2 PR 9).

### D-7 The privacy lawyer's list
- **Status:** reviewed 2026-11-12, left for later. not yet asked. Needed before the pilot (Milestone 7).
- **Questions collected so far:** is "strip email, phone and name, keep results and demographics" anonymous enough in the US, UK and India (age, gender, company and exact dates can identify someone in a small company); what the privacy text and disclosure page must say (the wording now on the site is listed under D-17); how long erased data may stay in RDS backups (30 days today); enterprise data agreements; D-2 and the founder's "keep the membership link on erasure" choice; consent and verifiable parental consent for under-18s in India (minors do not take the survey); transfers to the US, a UK representative and ICO registration; India's DPDP Act (substantive duties from 2027-05-13); consent, an unsubscribe link and `List-Unsubscribe` for bulk email (for example a feedback request to everyone who took the survey), which would be sent in batches through the Milestone 5 queue; data minimisation (an age band, optional gender) before demographics are collected; an invite sent to someone who never made an account keeps their address on the invite row, and the erase page works on accounts, so there is no admin tool yet to remove it; the privacy page itself (`/privacy/`, `templates/privacy.html`), which the founder chose on 2026-11-13 to publish from the facts before any legal review, and which says among other things "We do not sell your information"; the draft procedure for deletion requests (`08-deletion-requests.md`, Milestone 6), in particular who may ask, whether erasing within 30 days of a request is soon enough everywhere the site is used, and that an organization's admin may already have downloaded a file with a member's name and email address in it; Stripe keeps the email address a receipt was sent to, as the payment processor, after the person is erased here (Milestone 4b).
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
- **Changed again on 2026-11-13, at the founder's word:** that last sentence now says plainly whether a licence comes with the invite or the code. With one: "Joining makes you a member. This invite comes with a licence to take the survey for <organization>." ("This code comes with…" for a code.) Without: "Joining makes you a member. To take the survey for <organization> you also need a licence from it, which it may give you later." The tier is not named. Include it in the later review.
- **When the wording changes:** the four "admins can also see" survey lines must stay the same on both pages (the join page says "that survey" where the other says "this survey"); `tests/test_join_pages.py` compares the two files and fails if they drift. `tests/test_survey_context_pages.py` and `tests/test_join_pages.py` also quote the wording.
- **Changed since the founder read it (Milestone 4 PR 4, 2026-11-13):** the last sentence of the join confirmation page. It said "Joining makes you a member. It does not by itself give you a licence to take the survey", which stopped being true once an invite or a join code could carry a licence. It now says "Joining makes you a member. To take the survey for <organization> you also need a licence from it. It may give you one as you join, or later." The lists of what admins can and cannot see are unchanged. Include this sentence in the later review.
- **Source:** raised with the founder on 2026-11-13 after Milestone 3 PRs 7 and 10.

### D-20 Sales tax and invoices, reviewed with an accountant
- **Status:** raised by the founder on 2026-11-13 while answering the payments basics: "do whatever makes sense for now, mark it as something to review later". **Decision:** the founder's, with an accountant. Needed before real prices are set, which is before real Stripe keys.
- **Today's default (Milestone 4b builds this):** no sales tax is collected. The checkout is built so that Stripe's tax setting can be switched on without a code change. A person gets Stripe's emailed receipt; an organization gets a numbered invoice as well.
- **A second question, raised 2026-11-13:** when opening the Stripe account the founder was offered "Managed Payments", where Stripe is the merchant of record and carries sales tax, fraud and disputes for an additional 3.5% of each sale, and skipped it. The checkout was not built for it. It is the same question from the other side (who is responsible for tax), so decide the two together, with the accountant or the lawyer. Choosing it would mean a change to how a purchase is started (`apps/payments/stripe_api.py`), not a redesign.
- **Questions for the accountant:** does the founder's home state, or any state where customers are, tax this kind of sale (an online assessment and its results); at what volume of sales in another state does a duty to collect begin; what an invoice to a business must show; whether the $1, $2, $3 placeholder prices are before or after tax once real prices are chosen.
- **If tax must be collected:** switch on Stripe's tax setting **[console]** (Stripe's dashboard, not AWS), register where required, and set `STRIPE_AUTOMATIC_TAX` to `true` in Parameter Store. Buying then needs no code change. **Refunds do:** the Refund button sends back the price before tax, because the site's record holds the price before tax, so the tax part of a refund would stay with Accelerare. That is a small change to `payments.services.refund` (refund the tax too), to be made before the setting is switched on. Record the answer in the decision log of `05-build-plan.md`.
- **Source:** the founder's answers of 2026-11-13; `05-build-plan.md`, Milestone 4b.

### Small things to revisit only if they come up
- **A stock licence's tier changed by staff:** in the Django admin, staff changing the tier of a licence that came from an organization's stock goes through the older `change_tier`, which does not check the stock, so staff can push a tier over what was bought. The page then says "12 of 10 given" and no more can be given at that tier, the same end state as lowering a stock below what is given (NOTES.md 2026-11-13). Add the check if staff ever do this by mistake.
- **Spelling:** the site says "licence" (British) and "organization" (US, the founder's choice on 2026-11-12). Pick one spelling for the whole site if anyone notices.
- SES **Mail Manager** (managed credential rotation) was not chosen; revisit if rotating the SMTP credential by hand becomes a chore.
- **allauth** was chosen for verification and later SSO; revisit if it fights the Milestone 3 join flows (`03-tech-stack.md` decision log).
- **A scratch database on the founder's laptop:** `accelerare_load`, in the local PostgreSQL, made on 2026-11-13 for Milestone 7's load check (500 made-up accounts). It touches nothing else. `docker compose exec -T db dropdb -U accelerare accelerare_load` removes it; keep it to repeat the measurements after a change.
- **Two join-code guesses at the same instant** from one account could count as one refusal (the count is read, then written). At ten an hour it makes no practical difference.
- **An organization with thousands of surveys:** its responses page lists them all on one page. Measured only up to 40 (Milestone 7). Add paging when an organization gets near a few hundred.
- **A very large download:** a CSV file is made inside the web request (Milestone 6), and the web server stops a request after 30 seconds. Nothing has been timed. If an export ever takes that long, make the file in the background worker and email a link; Milestone 7's load check is where to measure it.
- **A staff login with hand-picked permissions** (neither a superuser nor in the Support staff group) could be shown a link in the Django admin that answers "forbidden" (Milestone 6, PR 5). No such login exists; the two kinds that do are tested.
- **A disputed charge (a chargeback):** Stripe emails the account owner; the site is not told (the webhook listens for payments and refunds only). Staff then withdraw the licence by hand in the Django admin, or lower the organization's stock. Add the `charge.dispute.created` message if it ever happens more than once.
- **Refunding and erasing the same person at the same moment:** a refund locks the payment and then its licence; erasing an account deletes the licence and then empties the payment's link to it. If staff did both in the same instant PostgreSQL would stop one with a deadlock error and it would have to be repeated; nothing is lost.
- **Erasing and revoking at the same moment:** erasing an account and revoking one of its licences lock rows in opposite orders, so if staff did both in the same instant PostgreSQL would stop one with a deadlock error and it would have to be repeated (NOTES.md 2026-11-12). Nothing is lost. Fix the lock order if it is ever seen.
- **No favicon:** every page logs a 404 for `/favicon.ico`. Cosmetic; add an icon when there is a logo.
- **The licence form's tier box:** in the Django admin the tier is typed as a number (1 to 3) rather than picked from a list. Make it a dropdown if staff ever mistype it.
- **After "this invite was sent to another address":** the person is told to add and verify that address on their profile and open the link again; they are not brought back to the invite automatically.
- **Possible repeats:** organization admins have a "possible repeat" filter and mark, but nothing sets `Response.possible_repeat` until matching exists (Milestone 5).
- **Known refused edge:** account A has verified `x@`, but account B registered with `x@` and never verified it, so `x@` is B's login name and A's make-primary is refused (NOTES.md 2026-10-09).

## Later features

None of these is in a milestone. Each has a seam in the current design (`02-architecture.md`, "Deferred extension points"); building one is a new plan, not a redesign.

- **L-1 Payments.** Moved on 2026-11-13 to Milestone 4b, straight after Milestone 4; see the build plan. What follows is the earlier note, kept for what it decided ("Likely Razorpay for India" is deferred with India). Writes licences through the same services the admin uses (`grant_individual` with source `purchase`, the seat-pool services). Already decided: licences do not expire, a retake needs another licence, upgrades happen in place. Needs a payment ledger (amount, currency, date, invoice number, provider reference, licence id and tier) with no personal identity, so an erasure never removes an accounting record; refunds revoke through the service; the funnel records `licence_granted` with source `purchase`; reminders for unused licences once the worker exists. See `05-build-plan.md`, "Phase 3 stub".
- **L-2 SSO per enterprise** (SAML or OIDC), optional beside local accounts. FR-5. A second login method on the account; memberships unchanged.
- **L-3 Helper admin.** Requirements undefined. A third value in `membership.role` or a platform role table.
- **L-4 Dashboards and charts.** FR-21. Read-only queries over responses and results.
- **L-5 Algorithm, results and insights (Phase 2).** The seam is planned for Milestone 5: `apps/results/` with `compute_result` returning `None`, `visible_fields` and `recompute_results`. See `05-build-plan.md`, "Phase 2 stub", and D-6. A free account sees no results (decided 2026-11-13; was D-5).
- **L-6 Survey version 2.** New `SurveyVersion` and `Question` rows; old responses keep their version.
- **L-7 Phone verification by SMS.** Needs a paid SMS provider and per-country sender registration (India DLT takes weeks). Turning it on activates the verified-phone matching rule, which is inert until then.
- **L-8 Move to Mumbai (Phase 4).** `04-infrastructure.md`, "Moving to Mumbai"; SES must be set up and out of the sandbox in `ap-south-1` first; write Terraform at that point.
- **L-9 Latency for UK and India.** About 150 ms from the UK and 250 ms from India to Oregon. A CDN or the regional move if it becomes a real problem; one database in one region, with replicas if it grows.
- **L-11 A third linked login.** Since Milestone 5 a superuser can link two accounts that are the same person, and undo it. A login that is already linked cannot be linked to a third (`apps/matching/services.py`, `_who_moves`): with two at most, every link is one row and "undo" is exact. Allowing three or more means deciding what undoing one link does to the others. Build it when a real case appears; until then the superuser is told why and can choose the better pair.
- **L-12 Same-name check at scale.** The same-name rule (`apps/matching/rules.py`, `same_name`) reads the number and name of every account that belongs to an organization and compares names in Python, because PostgreSQL cannot remove accents without the `unaccent` extension. It runs in the background worker and is fine for thousands of members. Past that, store the comparison form of the name in an indexed column on `Account` and compare in the database.
- **L-10 Email through Microsoft Graph.** No redesign: a small backend class behind `MAILERS["default"]["BACKEND"]` plus an Entra app limited to one mailbox. Only if SES is ever unsuitable.
