# Location manager guide

You look after one outlet (or a few). In ResolveDesk you review the remedies the system proposes
for customer problems at your outlets, approve or reject them, and follow every case through to
the end. You only see orders, cases and proposals for **your** outlets.

## Signing in

1. On the **Sign in** page, choose your **Business**, enter your work **email** and **password**,
   and click **Sign in**.
2. You land on **Approvals**.

"Wrong email or password" means one of them is wrong. After five wrong tries you are locked out
for a few minutes. If you see **"Your session has ended"**, sign in again. Click **Sign out** (top
right) when you leave a shared device.

The top bar shows your business, your name, your role badge (**Location manager**), **Help** and
**Sign out**. The left menu (a row of tabs on a phone) has **Approvals**, **Cases** and **Help**.

## Approvals

**Approvals** is your queue: remedies waiting for a person's decision, oldest first. Each row
shows:

- **Category**: what the customer reported (for example *Missing items*). A red **Checks failed**
  badge means it can't be approved as it stands;
- **Order**: the order number;
- **Outlet**: where the order was made;
- **Action** and **Amount**: what the system proposes, for example *Refund ₹180.00*;
- **Risk**: *Low*, *Medium* or *High*, set by the kind of action (refunds are higher risk than
  vouchers);
- **Age**: how long it has been waiting.

Click **Review** (or the card, on a phone) to open it.

Use the **Outlet**, **Action** and **Sort** menus above the list to narrow it (sort: *Oldest first*, *Newest first*, *Highest amount*). The Outlet menu only lists your own outlets. Your choices stay in the page address, so a reload keeps them. If nothing matches, the page says so.

## Reviewing a proposal

The review page shows everything you need to decide:

1. **Customer's message**: what the customer wrote, in their own words. Treat it as a claim, not a
   fact.
2. **Why this was proposed**: the reason, in plain words, based on the order's records.
3. **Policy cited**: chips like `missing_items_v2#1.2 · v2` naming the policy sections used. Policy
   text is reference only: the amount always comes from your business's configured rules.
4. **Checks**: a list with ✓ (passed) or ✗ (failed), for example that the amount is within the
   limit and the order belongs to the customer. Any problems are listed under the checks.
5. **Proposal**: the action, the amount, the order total, and when it was proposed. **Open the
   case** shows the customer's view and the audit trail.

## Approving or rejecting

1. Optionally type a **Note**. It is saved with your decision.
2. Click **Approve** or **Reject**.
3. Read the confirmation (for example "Approve refund of ₹180.00 for order O0001234?") and click
   **Yes, approve** or **Yes, reject**. Click **Cancel** to go back.

What happens next:

- **Approved refund**: it is sent to the payment provider. The case shows *Processing* until the
  provider confirms, then *Confirmed*. The customer is never told the money is paid before that.
- **Approved voucher**: the case moves on and the customer is told when it is issued.
- **Rejected**: the customer's case shows *Declined*.

Messages you may see:

- **"Needs a senior approver"**: the amount is above your approval limit. Leave it in the queue
  for the owner or HQ.
- **"Someone has already decided this proposal"**: another manager got there first. Nothing more
  to do.
- **Approve is greyed out**: the checks failed. You can still reject it.

An approval is tied to exactly the proposal you saw. If the proposal changes, or the approval is
not used within a few hours, it expires and has to be approved again.

## Cases

**Cases** lists every case at your outlets, newest first, with a coloured stage badge. Use the
**Stage** filter to see, for example, only cases *Awaiting approval* or *With our team*.

Click a case to open it. You see what the customer sees (the progress bar, the current message,
the remedy and the timeline) plus an **Audit trail** at the bottom. Click it to expand the raw
record of every step: who or what acted, when, and the details. Personal details are hidden.

### Stages

| Stage | Meaning |
| --- | --- |
| Received | The report has been logged. |
| Investigating | The assistant is checking the order's records. |
| Waiting for your reply | The customer has been asked a question. |
| Awaiting approval | A remedy is waiting in the Approvals queue. |
| Processing | Approved and being carried out (a refund sent to the provider). |
| Confirmed | Finished: the provider confirmed the refund, or the voucher was issued. |
| Declined | No remedy was approved. |
| With our team | Escalated to a person, for example when the facts are unclear. |
| Closed | Finished with no further action. |

## Growth

If **Growth** is in your menu, you can see outlets with falling repeat customers and propose or
approve a win-back campaign for your outlet. Sending needs two different approvers, one of them
an HQ owner; the screen shows who has approved so far and any reason the system refuses.

## What the AI does and doesn't do

- It **reads** the order's records and your policies, and **proposes** a remedy within your
  business's rules.
- It **cannot** pay or change anything. Only an approved proposal is carried out, by the system,
  once.
- People approve every refund. Only small vouchers under your business's limit may be approved
  automatically.
- It never tells a customer money is paid until the payment provider confirms it.
- When it is unsure, it asks the customer a question or hands the case to a person (*With our
  team*).
