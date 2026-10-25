# User manuals

One manual per role. The web app shows the signed-in user's manual on its **Help** page; these
files are bundled into the app at build time (`web/src/manual/index.ts`), so edit them here.

| Role | Manual | Who |
| --- | --- | --- |
| Customer | [customer.md](customer.md) | People who order and report problems |
| Location manager | [location_manager.md](location_manager.md) | Run one or a few outlets; approve within their limit |
| Franchisee owner | [franchisee_owner.md](franchisee_owner.md) | Own one or more outlets; approve within their limit |
| HQ owner | [hq_owner.md](hq_owner.md) | See every outlet; senior approver |

Keep every manual true to the app: when a screen, label or stage changes, update the manuals in
the same change.
