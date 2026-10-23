"""In-process fakes of external systems (payment, messaging, POS, delivery app) with failure
injection. Connectors talk to these through the same interface a real client would expose;
agent tools never call them directly (PROJECT.md section 10)."""
