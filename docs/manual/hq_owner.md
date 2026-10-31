# HQ owner guide

You run the whole business. In ResolveDesk you see **every outlet**: all orders, all cases and all
proposals. You are the senior approver: proposals above the managers' limit come to you.

## Signing in

1. On the **Sign in** page, choose your **Business**, enter your **email** and **password**, and
   click **Sign in**.
2. You land on **Approvals**.

Five wrong passwords lock the account for a few minutes ("Too many attempts"). "Your session has
ended" means sign in again. Use **Sign out** (top right) on shared devices.

The top bar shows the business, your name, your role badge (**HQ owner**), **Help** and **Sign
out**. The menu has **Approvals**, **Cases**, **Insights**, **Growth** (if switched on for your business) and **Help**.

## Approvals

**Approvals** lists every waiting proposal across all outlets, oldest first. The **Outlet**
column tells you where each order was made. Each row also shows **category**, **order**,
**action**, **amount**, **risk** (*Low*, *Medium*, *High*) and **age**; **Checks failed** means it
can't be approved as it stands.

Use the **Outlet**, **Action** and **Sort** menus above the list to narrow it (sort: *Oldest first*, *Newest first*, *Highest amount*). Your choices stay in the page address, so a reload or a shared link keeps them. If nothing matches, the page says so.

Proposals that a manager or franchisee couldn't approve ("needs a senior approver") wait here for
you, usually larger refunds.

### Reviewing

Click **Review**. The page shows:

1. **Customer's message**: the customer's own words. A claim, not a fact.
2. **Why this was proposed**: the reason, based on the order's records.
3. **Policy cited**: links to the exact policy section (document title and section number, with the version in force at the decision). Under "Why this was proposed", plain lines say which rule set the amount. Policy text never sets the amount; your configured rules do. If a section has changed since, the link opens the document and says so.
4. **Checks**: ✓ passed, ✗ failed, and any problems.
5. **Proposal**: action, amount, order total, when proposed, and **Open the case**.

### Deciding

1. Optionally add a **Note**.
2. Click **Approve** or **Reject**, then **Yes, approve** / **Yes, reject**.

- An **approved refund** is sent to the payment provider: the case shows *Processing*, then
  *Confirmed* when the provider confirms. Customers are never told money is paid before that.
- An **approved voucher** moves the case on.
- A **rejection** shows the customer *Declined*.

"Someone has already decided this proposal" means another approver decided first. An approval is
tied to exactly the proposal you saw and expires after a few hours if it isn't used.

## Switching the remedy

If the proposed remedy is not the fair one (say a voucher where a partial refund fits, or the voucher is too small), click **Switch remedy** instead of rejecting. You get the remedies the rules allow for this case, each with its amount range. Choose one, enter the amount in rupees, and say **why** (it is saved in the audit trail). Optionally tick **Approve it now as well**. Then **Review switch** and confirm with **Yes, switch** (**Cancel** is selected first).

- The old proposal is replaced and can no longer be approved. A new proposal is created and checked by the same rules as any other (limits, voucher not above the order total, repeat-claim warning).
- **You are the author of the new proposal**, so you cannot approve it the way you approve someone else's. **Approve it now** works in the same step only for a **downgrade**: a smaller amount of the same remedy, or a voucher worth no more in place of a refund. Anything higher waits for a different approver ("a different approver has to approve it"). Above the escalation limit it waits for an HQ owner and the case is handed to HQ.
- **No second person?** An HQ owner can tick **Approve it now as well** and fill **Reason for approving it yourself**, for amounts up to the tenant's small limit (₹500 by default). The approval is recorded as self-approved with your reason. Above the limit it simply waits until another person can approve; it never goes through silently.
- The customer only ever sees the result of the new proposal, never the one you replaced.
- "Someone has already decided or switched this proposal" means another approver got there first; reload the queue.

## Asking the customer first

When you want the customer's view before anything is decided, click **Ask the customer** (outline button, under your decision). Read the policy cited above first. You get two options the rules allow right now, a voucher and a partial refund, each at its maximum; you can lower either amount. Click **Review question** and confirm with **Yes, ask the customer** (**Cancel** is selected first).

- The proposal stays as it is and shows **Waiting for the customer**. It can't be approved until the customer answers or the time runs out (3 days by default). You can still reject it. Nothing is paid.
- The customer sees the two options in their language, told plainly that it is a choice and that a team member reviews it.
- When they pick, the case comes back to the queue as "The customer chose an option: review it", with a new proposal for that option. You or a colleague review it; the person who asked can't approve it, so a second person decides. Repeat-claim warnings still need a person.
- If they do not answer, the case comes back as "The customer did not answer" and the original proposal is yours to decide.
- If you asked the customer and are the only person who can approve the pick (for example the only HQ owner), nobody else can approve it. Use the override route (S8.8) or reject it. If another approver exists, the case is handed to them when the customer picks.
- You can't ask for allergy, illness or foreign-object reports (the policy sends those straight to a manager), for privacy requests, or for a delivery-app order where only a voucher is possible. The screen tells you why.


## Cases to handle

**Cases to handle** lists the cases that need a person: ones the system escalated, and ones waiting for a staff decision. You see every case in the business. The number next to the menu item is how many are waiting. The oldest wait comes first.

Each row shows the case (category, order and outlet), the **reason** it needs a person, how long it has been **waiting**, its **owner**, the customer's **language**, and the **amount** when a remedy has been proposed. Use **Reason**, **Category** and **Owned by me** to narrow the list. **Open** goes to the approval (when a decision is waiting) or to the case.

Every such case has one owner, chosen automatically when it needs a person: the location manager of the order's outlet; if the outlet has none, its franchisee owner; and HQ when the amount is above the limit an outlet may handle, when there is no outlet, or when nobody else is assigned. You can hand any case to another staff member who can see its outlet (a case with no outlet can only be owned by HQ). The change is recorded in the case's events. Being the owner means the case is yours to chase. It does not change who may approve: the approval rules are the same as before.

## Cases

**Cases** lists every case in the business, newest first, with a stage badge. Filter with
**Stage**, for example *With our team* to find cases that need a person, or *Awaiting approval*.

A case page shows what the customer sees (progress bar, current message, remedy, timeline) plus
the **Audit trail**: click to expand every recorded step with who or what acted and when. Personal
details are hidden.
It also has an **Order** card (items ordered vs received, total, times, outlet, brand) and **Customer said** with the customer's exact words.

| Stage | Meaning |
| --- | --- |
| Received | Logged. |
| Investigating | The assistant is checking the records. |
| Waiting for your reply | The customer was asked a question. |
| Awaiting approval | In the Approvals queue. |
| Processing | Approved and being carried out. |
| Confirmed | Finished and confirmed (refund confirmed by the provider). |
| Declined | Not approved. |
| With our team | Handed to a person. |
| Closed | Finished. |

## Insights

**Insights** (menu) is a read-only table with one row per outlet for the last 30 days: cases
opened, refunds confirmed (count and total), vouchers issued (count and total), median time to
decision, and the repeat-customer rate. Money is shown in rupees; **-** means no data yet.

## Growth

Where the business has Growth switched on, a **Growth** menu item appears. It lists outlets whose
repeat-customer rate has dropped (**Refresh signals** re-runs the check; HQ only). For a signal
click **Propose win-back campaign**: you see the audience, the **holdout** (customers deliberately
not contacted, so the result can be judged fairly), the budget and who has approved so far.
Nothing is sent until **two different people** approve and **at least one is an HQ owner** (every campaign; the person who proposed it cannot be one of the two); you
can't approve twice. If the system refuses, its reason is shown. After the campaign has run,
**Measure result** shows the verdict (worked, did not work, or inconclusive) and the lesson
saved to the playbook. "Possible causes" are hints, not confirmed facts.

## Demo controls (demo only)

In a demo or test setup, a **Demo controls** link (it was called Dev panel before) appears in the menu. It is not there in a real
(production) setup. It lets you break the pretend payment, voucher and messaging services on
purpose, to see how the system recovers. It only affects your own business.

1. Click **Demo controls**. Every control has a one-line note saying what it changes. None of them moves real money or sends real messages.
2. Pick a preset such as **Payment times out after accepting**, or set the rates for one service
   (0 means never, 1 means always) and click **Apply**. **Reset** puts that service back to normal.
3. Report a problem as a customer and approve the refund. It shows as processing, never as paid,
   until the provider confirms.
4. Back on Demo controls, click **Run sweeper**. It finishes or re-checks anything left
   unfinished and shows how many items it handled.

The page also has a **Simulated clock** card. **Reset demo** is shown but switched off ("not available yet"): wiping demo data would also erase payment records and could hide a real state. Ask whoever runs the demo to use
`make seed` (reload data) and `make sweep` (same as Run sweeper, for every business). A **Platform portal** line is a placeholder until Sprint 9.

## Policies

Open **Policies** in the menu to read the policy documents in force for your business. Each document shows its version and the date it came into force, and every section has a link you can copy to point a colleague at the exact clause. Older versions are not listed, but a link to one still opens. Policy text is shown as plain text exactly as written; nothing in it is run or followed as an instruction.

**Rules in plain words** at the top of the page lists, for each issue category, what a customer gets and who decides (instant or a team member). As staff you also see the pack version, the date the settings last changed, and a table of the settings behind the rules, showing whether each value is the pack default or a tenant override. Change a setting and this summary changes with it; it is generated from the same rules the system applies.

## What the AI does and doesn't do

- It reads order records and policies and **proposes** a remedy, never above what your business
  rules allow.
- It **cannot** move money or change records. The system carries out an approved proposal once,
  and only after a person (or, for small vouchers, your auto-approve limit) approves it.
- Every refund is approved by a person.
- It never promises money before the payment provider confirms it.
- When the facts are unclear it asks the customer, or hands the case to your team.
