# Franchisee owner guide

You own one or more outlets. In ResolveDesk you see every order, case and proposal at **your**
outlets, approve or reject remedies, and keep an eye on how problems are being handled. You use the
same screens as a location manager.

## Signing in

1. On the **Sign in** page, choose your **Business**, enter your **email** and **password**, and
   click **Sign in**.
2. You land on **Approvals**.

Five wrong passwords lock the account for a few minutes ("Too many attempts"). "Your session has
ended" means you need to sign in again. Use **Sign out** (top right) on shared devices.

The top bar shows your business, your name, your role badge (**Franchisee owner**), **Help** and
**Sign out**. The menu has **Approvals**, **Cases**, **Insights**, **Growth** (if switched on for your business) and **Help**.

## Approvals

**Approvals** lists remedies waiting for a decision at your outlets, oldest first: **category**,
**order**, **outlet**, **action**, **amount**, **risk** (*Low*, *Medium*, *High*) and **age**. A
**Checks failed** badge means it can't be approved as it stands.

Use the **Outlet**, **Action** and **Sort** menus above the list to narrow it (sort: *Oldest first*, *Newest first*, *Highest amount*, *Expiring soon*). Your choices stay in the page address, so a reload or a shared link keeps them. If nothing matches, the page says so.

Open one with **Review**. The page shows:

1. **Customer's message**: the customer's own words. It is a claim, not a fact.
2. **Why this was proposed**: the reason, based on the order's records.
3. **Policy cited**: chips naming the policy sections and versions used. Policy text never sets
   the amount; your configured rules do.
4. **Checks**: ✓ passed, ✗ failed, with any problems listed underneath.
5. **Proposal**: action, amount, order total, when proposed, and a link to the case.

### Deciding

1. Add a **Note** if you like (saved in the audit trail).
2. Click **Approve** or **Reject**, then **Yes, approve** / **Yes, reject** to confirm.

After you decide:

- an **approved refund** goes to the payment provider. The case shows *Processing*, then
  *Confirmed* once the provider confirms. Customers are never told money is paid before that;
- an **approved voucher** moves the case on;
- a **rejection** shows the customer *Declined*.

If you see **"Needs a senior approver"**, the amount is above the limit your role can approve
(large refunds need HQ). **"Someone has already decided this proposal"** means another approver
decided it first. Approvals bind to exactly what you saw and expire after a few hours if unused.

## Cases

**Cases** lists every case at your outlets with a stage badge; filter with **Stage**. A case page
shows the progress bar, the current customer message, the remedy, the timeline and a collapsible
**Audit trail** of raw events (personal details hidden).

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

## Insights and Growth

**Insights** shows a read-only table for your outlets over the last 30 days: cases opened,
refunds confirmed, vouchers issued, median time to decision and repeat-customer rate (**-** means
no data). If **Growth** is in your menu you can propose a win-back campaign for a flagged outlet
and approve it, but sending also needs a second, different approver and an HQ owner's approval.

## What the AI does and doesn't do

- It checks real order records and proposes a remedy **within your business's rules**.
- It **cannot** move money. People approve refunds, and the system carries out each approved
  proposal exactly once.
- Only small vouchers under your business's limit can be approved automatically.
- It never promises money before the payment provider confirms it.
- When it is unsure, it asks the customer or hands the case to a person.
