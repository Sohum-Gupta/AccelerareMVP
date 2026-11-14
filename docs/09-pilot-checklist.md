# Pilot checklist — before and during the first customer

As of 2026-11-13 · Written with Milestone 7 · Depends on `05-build-plan.md` (Milestone 7), `06-backlog.md` and `04-infrastructure.md`

This is the list of things that only the founder can do before a first real organization uses the site, and how to bring that organization on. Milestone 7 built what could be built in code; what is left needs the AWS console, a deliberate fault on the live site, a lawyer, or a customer.

Steps marked **[console]** need the AWS console. Steps marked **[SSH]** need a terminal on the server. Everything else is in the Django admin or in a browser.

## Part 1 — Before any real customer's data

Do these in any order. Each has an entry in `06-backlog.md` with the detail.

| Done | What | Where | Backlog |
| --- | --- | --- | --- |
| [ ] | Turn on MFA for the `founder` AWS login | **[console]** IAM | T-6 |
| [ ] | Restore a database backup once, and write the date in the runbook | **[console]** RDS; `04-infrastructure.md`, section 9 | T-8 |
| [ ] | Make the CloudWatch alarms (server CPU and status, database storage and CPU), and confirm the billing alert | **[console]** CloudWatch | T-7 |
| [ ] | Add a second uptime monitor on `/health/worker`, and set both to wait one minute before alerting | Better Stack | T-26 |
| [ ] | See Sentry receive a test error from the site and from the worker (Part 2 below) | Django admin, then Sentry | T-28 |
| [ ] | Stop the web container once and see the uptime alert arrive (Part 3 below) | **[SSH]** | T-28 |
| [ ] | Choose the inbox that people can write to, and set `CONTACT_EMAIL` so the privacy page prints it | **[console]** Parameter Store, then a deploy | T-14 |
| [ ] | Get Amazon SES out of its sandbox, so invites reach addresses AWS has not verified | **[console]** the open AWS case | T-4 |
| [ ] | Have the privacy lawyer read the privacy page, the deletion procedure and the wording members see | A lawyer | D-7, D-17 |
| [ ] | Decide the site's real address | GoDaddy, **[console]** | D-11 |
| [ ] | Review tax and invoices with an accountant, then real prices and Stripe's live keys | An accountant; Stripe; **[console]** Parameter Store | D-20 |
| [ ] | Decide whether to close the SSH port | **[console]**; a change to the deploy | T-29 |

Two of these stop a pilot outright if they are not done. While SES is in its sandbox, an invite to a stranger's address is not delivered (T-4). And while the privacy page prints no address, a person has nobody to write to (T-14).

## Part 2 — See an error arrive in Sentry

**This raises a Sentry alert on purpose.** If Sentry emails you about new errors, you will get an email. Nothing else is affected, and no customer sees anything.

1. Django admin, "Background jobs". At the top right, press "Send a test error…". Read the page.
2. Press "Send the test error". You see the site's "Something went wrong" page. That is the test working. Go back.
3. Open Sentry. Within a minute there are two new errors named `DeliberateError`:
   - one from the web site. Open it: under "User" it shows an id, which is your account's number, and no email address or name;
   - one from the worker, a line that reads "Job (number) (test_error) failed on try 1 of 5: DeliberateError".
4. Back in "Background jobs", the row "test_error" says "Waiting" with 1 try. About two minutes later, reload: it says "Done" with 2 tries. Nothing is left as failed.

If only one of the two errors arrives, note which. If none does, `SENTRY_DSN` in Parameter Store is empty or wrong (`04-infrastructure.md`).

## Part 3 — See the uptime alert arrive [SSH]

**This takes the site down for a few minutes. Do not do it on a day you are showing the site.** It is the one step here that needs a terminal on the server; `04-infrastructure.md` says how to connect.

1. On the server, in `/opt/survey`, run:

   ```
   docker compose stop web
   ```

2. Wait for Better Stack's alert to reach you (its check runs every three minutes). The site shows Caddy's own error, not the site's "Something went wrong" page, because nothing is running to draw it.
3. Start it again:

   ```
   docker compose start web
   ```

4. Open `https://app.theaccelerare.com/health`. It says "ok". Better Stack sends a "recovered" message.

## Part 4 — Bringing on the first organization

Everything here is in the Django admin or on the site. Nothing needs SSH or the AWS console.

1. **The customer's first admin signs up** on the site and verifies their email address. While SES is in its sandbox they will not get the email: mark the address verified for them in the Django admin, under "Login (allauth)", "Email addresses", with the action "Mark selected email addresses as verified".
2. **Create the organization.** Django admin, "Organizations", "Add organization": its name, and the account that will be its first admin.
3. **Give it its licences.** Either the admin buys them on the site (their organization's Licences page, "Buy licences"; on Stripe's test keys no money moves), or you set them by hand: open the organization in the Django admin and press "Licence stock…".
4. **Check the people limit.** An organization may bring in 25 people plus one for every licence it has bought. For more, raise "People limit" on the organization's page.
5. **The admin brings people in,** from their organization's pages: invites by email (each can carry a licence), or a join code to share (it can carry a licence for each person who uses it). Tell them a code is refused after ten wrong tries in an hour, so that they pass the code on exactly.
6. **Watch the first ten surveys come in.**
   - Django admin, the first page: "Surveys submitted in the last 7 days" goes up. "Background jobs that failed" stays 0 and "Background jobs waiting" does not stay red.
   - "Responses": search for the organization's name.
   - Ask the organization's admin what their own Responses page shows, and to press "Download as a spreadsheet (CSV)" once.
7. **After the first day,** look at Sentry for new errors, at "Background jobs" for anything failed, and at "Audit log" for what the organization's admin did.

## Part 5 — If something goes wrong

| What you see | Where to look |
| --- | --- |
| A person says "Something went wrong" | Sentry. The report shows the account's number; open that account in the Django admin. |
| An email did not arrive | Django admin, "Background jobs": a failed "send_licence_email" names the kind of error. "SMTPRecipientsRefused" is the SES sandbox (T-4). |
| The site is down | The uptime checker's alert; then the last "Deploy" run on GitHub; then `04-infrastructure.md`, "Routine operations". |
| A payment went through and no licence appeared | Django admin, "Payments", the filter "Needs attention". |
| Someone cannot join with a code | The code's row under "Join codes" says whether it is working, expired, switched off or used up. Ten refused tries in an hour makes that account wait an hour. |
| Someone asks for their account to be deleted | `08-deletion-requests.md`. |
