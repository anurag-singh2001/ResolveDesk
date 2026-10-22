# Decisions

One entry per design choice. Newest first.

Format:
## YYYY-MM-DD · Title
- Decision:
- Why:
- Alternative rejected:

## 2026-10-22 · LLM proposes, code executes
- Decision: Agents only get read tools; the executor is plain code acting on an approved, hash-bound proposal.
- Why: money and customer messages must be deterministic and auditable.
- Alternative rejected: giving the resolution agent a refund tool (unbounded risk, hard to test).

## 2026-10-22 · Row-level security for tenancy
- Decision: one database, `tenant_id` on every tenant-owned table, Postgres RLS with a session variable.
- Why: isolation enforced by the database even if application code has a bug.
- Alternative rejected: schema per tenant (heavier migrations, harder to demo onboarding).

## 2026-10-22 · Free LLM stack
- Decision: Gemini Flash main, Groq classifier + fallback, Ollama offline, local embeddings.
- Why: zero cost for a POC; provider switch shows production readiness.
- Alternative rejected: one paid provider.
