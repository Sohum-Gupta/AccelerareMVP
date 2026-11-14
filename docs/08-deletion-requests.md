# Deletion requests — how to handle one

As of 2026-11-13 · Written with Milestone 6 · Depends on `05-build-plan.md` (Milestone 6) and `06-backlog.md` (D-2, D-7, D-8)

**This is a draft.** It describes what the site does today and a sensible way to use it. A privacy lawyer has not read it (`06-backlog.md`, D-7). The parts a lawyer must confirm are marked *(to confirm)*. The site is built for the US first; nothing here claims to meet a particular law.

## In one paragraph

A person may ask for their account to be deleted. A superuser erases it in the Django admin with the "Erase this account…" button. If the person never finished a survey, everything about them is deleted. If they did, their email, phone, name and login are removed and the finished survey is kept with no link to a person. Either way it cannot be undone, and the audit log keeps a record of what was removed, as numbers. Nothing here needs SSH, GitHub or the AWS console.

## Who may ask

- **The person themselves,** writing from an email address that is verified on their account. *(The founder's decision, 2026-11-13; to confirm with the privacy lawyer, D-7.)*
- **Not an employer or an organization** on a member's behalf (the founder's decision, 2026-11-13: only the person can have their account deleted, and staff do it in the Django admin). An organization that wants someone out does not need a deletion. Its admin deactivates the member on the organization's Members page and takes back any unused licence on its Licences page; the person keeps their account. Tell the company that. A company that asks for the surveys taken for it to be deleted is a different question and is not decided (D-2); tell the founder that it came up.
- **Not somebody writing from an address the account does not have.** Ask them to write from the address they log in with, or to log in and add and verify the new address on their account page first.

There is no "delete my account" button for people themselves (D-8). A request reaches staff by email.

## How long it may take

Erase the account within **30 days** of the request (the founder's decision, 2026-11-13).

The window is there on purpose. Erasing takes a minute and cannot be undone, so the 30 days give the person time to say the request was a mistake. Until the account is erased, they can withdraw the request by writing again. There is no need to erase on the day the request arrives.

When a request arrives, write back the same week: say it was received, that the account will be erased within 30 days, and that they can cancel until then.

## Steps, in the Django admin

You need a superuser login. Support staff cannot erase.

1. **Find the account.** "Accounts", and search for the email address the request came from.
2. **Check who is asking.** Open the account. Under "Contact points", the address the request came from must be listed with a date under "Verified at". If it is not, stop and write back (see "Who may ask").
3. **Look at what the account has.** The "Related" line shows its memberships, licences, surveys and payments.
4. **Press "Erase this account…"** at the top right. The page says which of the two outcomes will happen and lists, in numbers, what will go and what will stay. Nothing has happened yet.
5. **Type the account's email and a reason,** for example "deletion request, 2026-11-20". Do not type the person's email, phone or name into the reason: the reason is kept.
6. **Press "Erase permanently".** It cannot be undone.
7. **Check the record.** "Audit log", and type the account's number into the search box. The row `account.erased` shows who erased it, when, and what was removed, as numbers.
8. **Write back** to say it is done, what was removed and what was kept (below), and that copies in backups are gone within 30 days of the erasure.

## If the page refuses

The page says why, in plain words. The three reasons:

- **"This account is the only admin of (an organization), which still has other members."** Make another member an admin first: "Memberships", tick the member, choose "Make the selected members admins". Then erase.
- **"This is the last active superuser."** Another superuser must exist first.
- **"You cannot erase your own account."** Another superuser does it.

## What is removed

- The email addresses, the phone number, the name and the login (the password stops working, and the person is logged out everywhere).
- Any survey they had started and not finished.
- Licences they had not used: deleted with the account, or revoked if the account is kept.
- Their address on any invite an organization sent them.
- Anything they typed in the box under "Yes, I have taken this survey before".
- Any "possible duplicate" they were part of.
- Their email in the Django admin's history, which is replaced by "Account #(number)".

If the person never finished a survey, their account, their memberships of organizations and their licences are deleted as well, and nothing is left.

## What is kept, and why

- **A finished survey, with no link to a person:** the answers, the dates, the tier and the answer to "have you taken this before". Kept for aggregate insights (the founder's rule of 2026-10-09). *(to confirm: whether what is kept is anonymous enough, especially in a small organization.)*
- **The membership of an organization,** deactivated. The organization's admins see "Erased member" with no name or address, and the survey still counts in their total (the founder's choice of 2026-11-12). *(to confirm)*
- **The audit log.** It holds account numbers and plain facts, never a name, an email address or an answer.
- **The record of a payment.** It holds an amount, a date and Stripe's reference, and no identity.
- **The funnel counts.** They never had a link to a person.
- **If the account was one of two linked logins,** the other login keeps working and keeps its own licences. The erase page says so.

## What an erasure does not reach

Say these plainly if the person asks.

- **Database backups.** Erased data stays in the automatic backups until they expire, 30 days later (`04-infrastructure.md`). *(to confirm)*
- **Files already downloaded.** An organization's admin may have downloaded the list of who took the survey for that organization: it holds the member's name and email address, and never their answers. The staff file with answers holds account numbers only, no name and no address, so it names nobody. Every download is in the audit log (`responses.exported`), with who took it and when.
- **Stripe.** If the person bought a licence, Stripe keeps the address its receipt went to, as the payment processor.
- **Emails already sent** to the person stay in their own inbox.
- **An invite sent to someone who never made an account** keeps their address on the invite, and there is no admin tool yet to remove it (on the lawyer's list, D-7). Withdrawing the invite does not remove the address.

## Where this is in the code

`apps/accounts/erasure.py` decides what is deleted and what is kept, in one place. `plan_erasure` says what would happen; `erase_account` does it, in one transaction, and writes the audit row. The list of what is stripped is one function, `_anonymise`, so a lawyer's "also remove X" is a small change. `tests/test_erasure.py` and `tests/test_erasure_summary.py` hold it to account.
