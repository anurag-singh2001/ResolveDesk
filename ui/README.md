# Demo UI

Plain Streamlit front end for the demo. It only talks to the HTTP API (`ui/api_client.py`);
the tenant YAML files are read just to build the dev login picker.

## Run the demo

Needs a filled-in `.env` (database URLs, `DEMO_AUTH=true`) and a migrated, seeded database
(`make migrate`, `make seed TENANT=all`).

1. Terminal 1: `make api` (FastAPI on http://localhost:8000)
2. Terminal 2: `make ui` (Streamlit on http://localhost:8501)

Set `API_URL` if the API runs somewhere else. Demo passwords come from each tenant folder
(`demo_password` in `tenants/<slug>/tenant.yaml`, optionally per user); `make seed` hashes them
into the database only when `DEMO_AUTH=true`.

## What's there

- **Customer:** pick an order, choose what went wrong, describe it, "Report a problem".
  "My cases" shows each case's stage bar and the API's status text, word for word.
- **Manager / franchisee / HQ:** pending approvals with amount, risk, reason and the code's
  eligibility checks; approve or reject with a note; "Reconcile refund" for refunds stuck
  in processing; a redacted timeline per case.
