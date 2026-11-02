# Demo script

About 15 minutes for the whole walk, or stop after Part 1 for the 5-minute version. It covers both
tenants and each role. Setup and reset are in [RUNBOOK.md](RUNBOOK.md); what each case type does is
in [SCENARIOS.md](SCENARIOS.md).

Status of this script: written from the code and the earlier README demo. Steps marked
**(browser-checked)** were walked through in a browser in earlier sprints. The rest are written
from the screens and have not been followed end to end by the owner yet; follow it once before
showing it to anyone.

## Before you start

1. `.env` has `APP_ENV=dev`, `DEMO_AUTH=true`, `ENGINE_MODE=agents` and working LLM keys.
   `MOCK_STATE_FILE=var/mock_state.json` keeps mock refunds across an API restart.
2. `make migrate`, `make seed TENANT=all`, `make api` (terminal 1), `make web` (terminal 2).
3. Open http://localhost:5173. The login page lists the demo accounts; pick one.
4. Optional, for the platform portal: set the four platform variables from the RUNBOOK and run
   `APP_ENV=dev uv run python -m scripts.seed_portal_demo` once. Those portal rows are labelled
   demo data; they are not real activity.

Accounts used:

| Tenant | Role | Name |
| --- | --- | --- |
| Spice Route | Customer | Kabir S., Riya M. |
| Spice Route | Location manager | Rohit Shinde (Kharadi) |
| Spice Route | HQ owner | Asha Kulkarni |
| BrewCo | Customer | Dev P., Ananya K. |
| BrewCo | Location manager | Neha Joshi (Baner), Arjun Mehta, Omkar Patil |
| BrewCo | Franchisee owner | Vikram Rao (Baner, Viman Nagar), Sana Shaikh (Aundh, Kothrud) |
| BrewCo | HQ owner | Meera Iyer |

## Part 1: support, the five-minute version

1. **Refund, approved and confirmed (Spice Route, browser-checked).**
   Sign in as *Kabir S.* → open a late order → report "My order came over an hour late and cold".
   The AI files it as late delivery and proposes a refund within the tier in force on the order
   date (for example 50%, ₹244.50 on a ₹489 order). Sign out; sign in as *Asha Kulkarni* →
   **Approvals** → **Review**: the customer's words, the cited policy section, and the checks.
   **Approve**. Back as Kabir the case ends at **Confirmed**; while the provider has not confirmed
   it reads *Processing*, never paid.
2. **Voucher, auto-approved (BrewCo, browser-checked).**
   *Dev P.* → report "My cappuccino was lukewarm and tasted burnt". Food quality → ₹100 voucher,
   under the ₹150 auto-approve cap → **Confirmed**, "Your voucher worth ₹100.00 has been issued."
3. **Outlet scope (BrewCo).** *Neha Joshi* (Baner manager) sees only Baner's cases;
   *Meera Iyer* (HQ) sees all five outlets; *Vikram Rao* sees his two.
4. **Payment timeout, shown honestly.** As an HQ owner open **Demo controls** and pick the preset
   **Payment times out after accepting**, then approve a refund as above: the customer sees
   *Processing*. Press **Reset** and **Run sweeper**: it reconciles by key and the case moves to
   **Confirmed** with one refund, not two. Rehearse once first.
5. **The AI asks, the customer answers (BrewCo, browser-checked).** *Dev P.* → report "Not sure,
   just describe it". The case stops at **Waiting for your reply**. Reply "my cappuccino was
   served cold and tasted burnt" → timeline shows *You replied*, then a ₹100 voucher → **Confirmed**.

## Part 2: more for each role

**Customer (either tenant).**
- **Our policies**: *Rules in plain words* at the top, then the documents with a link per section.
- **Privacy & data**: what we hold, marketing consent switch, readable download
  (**Print or save as PDF**), erasure request. Write to the AI in Hinglish or Hindi and the
  reply comes back in that language; there is no language picker.
- Staff-only screens are not in the menu.

**Location manager (BrewCo: Neha Joshi; Spice Route: Rohit Shinde).**
- **Approvals** and **Cases to handle**: only their outlet. Try **Switch remedy** and **Ask the
  customer** on a proposal.
- **Dashboard**: charts for their outlet; set **Period** to 90 days and **Week**; open **Table view**.
- **Segments**: counts by segment; hover a name for its meaning; small groups show *Hidden*.
- **Brand signals** is not in their menu (HQ only); say so if asked.

**Franchisee owner (BrewCo: Vikram Rao).**
- **Insights**: per-outlet table for the last 30 days.
- **Dashboard** with a **By location** table; click a name to drill in, **All in scope** to go back.

**HQ owner.** Both tenants have growth on; the BrewCo walk is the one the tests prove.
- **Dashboard**: **By brand** (Spice Route has three brands in one kitchen) and **By location**.
- **Segments**: use the **Brand** menu; read the WhatsApp column note (consent only).
- **Growth** (BrewCo, browser-checked): *Meera Iyer* → **Insights** (Baner stands out at about
  37% repeat rate) → **Growth** → **Refresh signals** → "Baner: repeat customers down" with the
  evidence and causes marked "not confirmed" → **Propose win-back campaign** (audience, holdout,
  budget) → **Approve**. Approving twice is refused. Sign in as *Neha Joshi* and approve → **Sent**.
  **Demo controls** → clock +15 days → **Growth** → **Measure result**: with 154 offered and 17 held
  out the verdict is honestly **Inconclusive** ("too few people to tell"). Reset the clock afterwards.
- **Return on the offer** appears under that campaign, with the offered and held-out groups and
  each send state kept separate. It says plainly when the window is still open or the groups are
  too small.
- **Campaign calendar**: the campaign's bar and status; the yellow note counts overlap and
  frequency-cap customers and blocks nothing. The same warning shows on the campaign before approval.
- **Brand signals**: each brand against its earlier repeat rate; low-volume brands are labelled,
  not charted.
- **Add spend by hand** (bottom of **Growth**): enter a channel, an amount in rupees and a date
  range, **Save spend**. It is kept as typed, is not verified, and is not part of campaign ROI.
- **Spice Route**: Growth is on, but the demo has only Asha (HQ) and Rohit (manager), and a
  campaign needs two approvers who are not its proposer. Show the screens; do not promise to
  complete a campaign there. That flow is not yet proven on Spice Route (S12.6).
- **Privacy requests**: staff list of customer download and erasure requests (HQ only).
- **Help**: the manual for the signed-in role.

**Platform operator (separate sign-in at http://localhost:5173/platform).**
- **Health**, **Scheduled jobs** (run history only; it cannot start a job), **Logs and alerts**,
  **AI performance**. On the demo the rows are seeded demo rows from `seed_portal_demo`, so say so.
- **Scenario lab**: pick a business, open a scenario, **Check** it; held-out scenarios are
  read-only. Running scenarios needs a scratch database and real model keys; do not run it live
  without a rehearsal (the last real run, S10.1, stalled).

## After the demo

Reset the simulated clock; clear chaos (**Reset**); `make sweep`. To reload data, `make seed
TENANT=all` (destructive, dev only).
