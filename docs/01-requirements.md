# Requirements — Survey Platform

As of 2026-10-05 · v2, amended in Planning Session 2 (Architecture)

## Purpose and scope

The platform collects answers to one fixed personality survey, stores every answer permanently, and lets individuals, enterprise admins and the startup view them. Insights from a separately built algorithm come later; the MVP ships without it.

Target market is India, with a US-hosted trial first. Customers are enterprises (companies, schools) buying seats for their members, and individuals buying for themselves. Minors do not take the survey.

| Phase | Delivers | Status |
| --- | --- | --- |
| 1 — MVP | Accounts, enterprise tenants, survey intake with save/resume, raw data storage, table-based viewing, CSV export, repeat-user flagging, manual tier assignment | Current |
| 2 — Insights | Algorithm integration, tiered insight delivery, results UI | Not started |
| 3 — Commercial | Self-serve payments (individual and enterprise), SSO, helper admin role, dashboards | Not started |
| 4 — India | Move hosting to ap-south-1 (Mumbai), DPDP review with counsel | Not started |

## Actors and roles

Five roles; four are in the MVP. Roles are per-enterprise for enterprise users, so one person can be a member of one enterprise and an admin of another.

| Role | Scope | Can do (MVP) | Cannot do |
| --- | --- | --- | --- |
| Individual user | Own account | Take and retake the survey, save and resume, view own responses | See anyone else's data |
| Enterprise member | Own account within an enterprise | Same as individual user; joins only via an invite or a code; may add a personal email and phone | Leave the enterprise's view of their data |
| Enterprise admin | One enterprise | Self-register the enterprise, invite members (email or code), see all member responses and results, assign tier seats, export CSV | See other enterprises, change platform settings |
| Platform root admin | Whole platform | Everything: all enterprises, all users, all responses, create enterprises, set tiers and seat pools, export | — |
| Helper admin | Deferred | Requirements undefined; design the role system so it can be added without a schema change | — |

Enterprise admins see individual members' answers. The survey must state this plainly before a member starts answering.

## Core domain concepts

The central decision: a person is separate from their enterprise memberships. Data is owned jointly by the person, the enterprise it was taken under, and the platform, and survives the person leaving the enterprise.

| Concept | Definition | Key rules |
| --- | --- | --- |
| Account | One login (email + password; SSO later) | At least one email and a phone number are required; a second email is optional and recommended for cross-employer identity |
| Person | The human behind one or more accounts, as best the system can determine | Auto-linked on verified email or verified phone; name only flags; links may be wrong and are reversible by root admin |
| Enterprise | A customer organisation (company, school) | Self-registers; has one or more admins, a set of members, and tier seat pools; starts with zero seats |
| Membership | A person's link to an enterprise, with a role (member or admin) | Can be deactivated when they leave; never deleted; data stays visible to enterprise and platform |
| Survey | The one fixed questionnaire, versioned | Version 1 only in MVP; responses record the version they answered |
| Response | One completed or in-progress run of the survey by one account under one context (enterprise or individual) | Stores raw answers permanently; status is draft or submitted; records survey version at submission; has no tier |
| Tier | One of three insight levels (1, 2, 3) | Same survey for all; results are computed in full and the viewer's tier filters what is shown. Can be bought before or after taking the survey |
| Entitlement | A tier granted to a person (individual purchase) or a membership (enterprise seat) | Source: seat, purchase, or manual; revocable; the only place tier is stored |
| Seat pool | Count of seats per tier an enterprise has bought | Admin assigns members to tiers; cannot exceed the pool; set manually by root admin until payments exist |
| Result | Output of the algorithm for one response | Phase 2; empty in MVP |

## Functional requirements (MVP)

Numbered so later docs and code can cite them. "Must" items block the MVP; "should" items ship if time allows.

**Accounts and auth**

1. FR-1 (must): A user can register with email and password, verify the email, log in, log out, and reset a password.
2. FR-2 (must): An account must have at least one email (personal or enterprise) and a phone number; a second email is optional. Email is verified at registration. Phone is collected but unverified in MVP (SMS verification deferred); only verified contact details take part in auto-linking.
3. FR-3 (must): Enterprise membership is granted only by accepting an email invite or redeeming a valid code. Email domains grant nothing.
4. FR-4 (should): An account can hold memberships in more than one enterprise at once.
5. FR-5 (deferred): SSO (SAML or OIDC) as an optional login method per enterprise.

**Enterprise management**

6. FR-6 (must): Any account can self-register an enterprise and become its first admin, with no manual review. Root admin sets the enterprise's seat pool per tier (manually until payments exist).
7. FR-7 (must): An enterprise admin can invite members by email (single-use link), or generate codes with a use cap and expiry (cap of 1 is a per-person code). Codes can be revoked. Each invite or code may carry a tier.
8. FR-8 (must): An enterprise admin can assign or change a member's tier, within the seat pool.
9. FR-9 (must): An enterprise admin can deactivate a membership. The member's responses stay visible to the enterprise and the platform.
10. FR-10 (must): A deactivated member keeps access to their own responses if they still have a working login (personal email or another membership).

**Survey intake**

11. FR-11 (must): The survey is one fixed, versioned set of questions, defined in data (not hard-coded in UI).
12. FR-12 (must): A user can start a response, save progress, leave, and resume later. Progress is saved on every page or every answer, not only on an explicit save.
13. FR-13 (must): A user can submit a response; a submitted response is immutable.
14. FR-14 (must): A user can retake the survey, creating a new response. All prior responses remain.
15. FR-15 (must): Before the first question, the survey shows who will see the answers (the enterprise, when applicable, and the platform).
16. FR-16 (must): The survey asks whether the respondent has taken it before, and where, as a self-report field.
17. FR-17 (must): Every response records survey version, context (membership or individual), and timestamps. Tier is not recorded on the response (see FR-34).

**Viewing and export**

18. FR-18 (must): Each role sees a filterable, sortable table of the responses in its scope (own, enterprise, all), with status, date, tier, and enterprise columns.
19. FR-19 (must): Clicking a response shows every question and answer in full.
20. FR-20 (must): Enterprise admins and root admin can export their scope as CSV.
21. FR-21 (deferred): Charts, aggregates, dashboards.

**Platform administration**

22. FR-22 (must): Root admin can view and search all accounts, enterprises, memberships and responses.
23. FR-23 (must): Root admin can merge two accounts it determines belong to one person, and undo the merge.
24. FR-24 (must): Root admin can delete an account and its responses on request, leaving an audit record of the deletion.
25. FR-25 (should): Every admin action is written to an audit log (who, what, when).

**Tiers and entitlements**

26. FR-34 (must): A tier is held as an entitlement on a person (individual purchase) or on a membership (enterprise seat). Results are computed in full and filtered on display by the viewer's entitlement. Entitlements can be granted before or after a response is submitted.

## Repeat-user identification

Matching is best-effort: the system flags likely repeats, never acts on them automatically, and accepts misses. What to do with a confirmed repeat is undefined and out of scope.

| Signal | Strength | Notes |
| --- | --- | --- |
| Same verified email on two accounts (any email field) | Strong | Auto-links the accounts to one person; reversible |
| Same verified phone number | Strong | Auto-links; inert until SMS verification exists (deferred) |
| Same unverified phone number | Weak | Flag only, until verification exists |
| Self-report "I have taken this before" (FR-16) | Strong intent, weak identity | Prompt for the email or company used before to help matching |
| Same normalised name + overlapping enterprise history | Weak | Flag only; common names in India make this noisy |
| Same normalised name only | Very weak | Do not flag on this alone |

Requirements:

1. FR-26 (must): On contact verification and on survey submission, the system runs matching, auto-links on verified email or phone, and records every candidate with the signals that fired.
2. FR-27 (must): Root admin sees all candidates (auto-linked and flagged), can confirm or reject flagged ones, and can undo an automatic link.
3. FR-28 (must): Enterprise admins see a "possible repeat" flag on a response, without seeing the other enterprise's data.
4. FR-29 (should): Matching rules live in one place so thresholds can change without touching intake code.

Resolved 2026-10-05: verified email and verified phone auto-link; name only flags.

## Algorithm integration boundary (Phase 2)

The algorithm is built outside this project and may arrive as code or as written instructions. The platform treats it as a pluggable, versioned function: one submitted response in, one result out, fast enough to run synchronously.

What the MVP must do so Phase 2 does not require rework:

1. FR-30 (must): Store raw answers in a form the algorithm can consume without transformation loss: question id, answer value, answer type, survey version.
2. FR-31 (must): Define a single interface in code (`compute_result(response) -> result`) with a no-op implementation in MVP. The results UI, when built, reads only from stored results, never calls the algorithm directly.
3. FR-32 (must): Results are stored with the algorithm version that produced them, so a corrected algorithm can be re-run over history and both versions kept.
4. FR-33 (should): Running the algorithm is a separate step from submission, so a failure in it never blocks a user from submitting.

Assumptions to confirm with whoever builds the algorithm:

- Input is one respondent's answers only; no cross-respondent data needed.
- Runtime is under a few seconds per response.
- Output is structured (fields, scores, categories), not free prose, so tiers can filter which parts are shown.
- It can be written in or called from Python.

## Non-functional requirements

Keep the MVP cheap and simple, but make the three things that are expensive to change later (data retention, region, deletion) correct from day one.

| Area | Requirement | Rationale |
| --- | --- | --- |
| Data retention | All raw answers and submitted responses kept indefinitely; nothing hard-deleted except via FR-24 | Business requirement; enables algorithm re-runs |
| Deletion | A root admin can delete one account's data on request within one working day; deletion leaves an audit stub | DPDP erasure rights; cheap now, costly to retrofit |
| Region | US (us-east-1) for trial; all region-specific values held in config so a move to ap-south-1 is a redeploy plus data migration, not a code change | Stated plan to ship in India |
| Hosting | AWS | Stated constraint |
| Cost | Minimise fixed monthly cost; prefer services that scale to zero or near-zero at low traffic. Budget to be set in the Infrastructure doc | Startup, pre-revenue |
| Scalability | Design for thousands of enterprises and hundreds of thousands of responses without re-architecture; do not build for that scale now | Stated "future scalability" |
| Security | Passwords hashed (bcrypt or argon2); HTTPS only; secrets in a secrets manager, never in code; role checks enforced server-side on every request | Baseline for any multi-tenant app |
| Tenant isolation | Every query scoped by enterprise; tested with automated cases that one enterprise cannot read another's rows | The most common and most damaging bug class in multi-tenant apps |
| Backups | Daily automated database backups, retained 30 days, restore tested once before launch | "All data must be stored" is meaningless without restore |
| Availability | Best effort; no SLA for MVP | Trial phase |
| Team | One developer, Python-first | Drives every stack choice toward boring, well-documented tools |

## Deferred scope and open questions

Deferred, but the MVP design must not block them:

- Payments: self-serve purchase for individuals and enterprises, likely Razorpay for India. Until then, root admin sets tiers and seat pools by hand after manual invoicing.
- SSO per enterprise (SAML or OIDC), optional alongside local accounts.
- Helper admin role with a reduced permission set.
- Dashboards, charts and aggregate views.
- Algorithm, results, and tiered insight display.
- Multiple surveys or survey versions beyond v1.

Open questions to resolve before or during the Architecture session:

- [x] Tier in MVP: resolved, tier is an entitlement at view time (FR-34); the survey has no tier.
- [x] Tier change after submit: resolved, entitlements can change any time; results are shown at the current tier.
- [x] Codes: resolved, both shared codes with a cap and per-person codes, plus email invites (FR-7).
- [x] Auto-link: resolved, verified email and phone auto-link; name flags.
- [x] Domain verification: resolved, no domains; invites and codes only (FR-3, FR-6).
- [x] Survey shape: resolved, 25 questions, each answered 1–5, no branching.
- [x] Languages: resolved, English only; strings externalised.
- [ ] Phone verification by SMS: deferred; needs an Indian SMS provider and DLT registration.

## Decision log

Decisions made in Planning Session 1 (2026-10-05), newest first. Later sessions append here.

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-10-05 | Tier is an entitlement on person or membership; the survey has no tier (Session 2) | Founder: same survey for all, pay before or after, show what is paid for |
| 2026-10-05 | Enterprises self-register; membership only via invite or code; no email-domain rules (Session 2) | Founder wants no manual review |
| 2026-10-05 | Verified email and phone auto-link accounts; name only flags (Session 2) | Founder decision |
| 2026-10-05 | Phone number and at least one email are mandatory at registration (Session 2) | Founder decision; improves repeat-user matching once phone verification exists |
| 2026-10-05 | Survey is 25 numeric 1–5 questions, no branching, English only (Session 2) | Stated by founder |
| 2026-10-05 | Data is jointly owned by person, enterprise and platform; it persists after a member leaves | Stated by founder |
| 2026-10-05 | Enterprises buy seat pools per tier, and can mix tiers across members | Stated by founder |
| 2026-10-05 | Repeat-user detection is best-effort flagging plus a self-report question; misses are acceptable | No reliable cross-employer identifier exists |
| 2026-10-05 | Enterprise email mandatory for enterprise members; personal email and phone optional | Superseded in Session 2: any email; membership via invite or code |
| 2026-10-05 | Enterprise admins see individual answers; the survey discloses this up front | Product decision plus basic fairness to respondents |
| 2026-10-05 | Host in US for trial, move to Mumbai for launch; region kept in config | Stated plan; avoids a rewrite later |
| 2026-10-05 | Payments, SSO, helper admin, dashboards deferred past MVP | Solo developer; MVP is intake and viewing |
| 2026-10-05 | MVP ships without the algorithm; a no-op interface is built in its place | Algorithm does not yet exist in usable form |
| 2026-10-05 | One fixed survey, versioned from the start | Stated by founder; versioning is cheap now |
| 2026-10-05 | Python is the primary language | Developer's strongest language |
