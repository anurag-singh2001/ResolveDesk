import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { CustomerOffer as Offer } from "../api/types";
import { RemedyChoice } from "./RemedyChoice";
import { Alert, Button, Card } from "./ui";

/**
 * Case page, customer only (S8.10): a team member asked the customer to choose between two
 * options. All text, amounts and timing come from the server in the case language; the pick is an
 * option code the server re-checks, and it promises nothing: a team member reviews it.
 */
export function CustomerOffer({ caseId, onChanged }: { caseId: string; onChanged?: () => void }) {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .caseOffer(caseId)
      .then((o) => {
        if (!live) return;
        setOffer(o);
        setValue(o.options[0]?.code ?? "");
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [caseId]);

  if (!offer || offer.state === "none") return null;

  if (offer.state !== "open") {
    return (
      <Card className="p-4">
        <p className="text-sm text-foreground">{offer.status_text}</p>
      </Card>
    );
  }

  async function send() {
    setBusy(true);
    setError(null);
    try {
      setOffer(await api.chooseOffer(caseId, value));
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <h2 className="font-montserrat text-sm font-semibold text-foreground">{offer.heading}</h2>
      <p className="text-sm text-foreground">{offer.intro}</p>
      <RemedyChoice options={offer.options} value={value} onChange={setValue} />
      <p className="text-xs text-muted-foreground">{offer.expires_note}</p>
      {error && <Alert>{error}</Alert>}
      <Button type="button" variant="soft" onClick={send} loading={busy}>
        Send my choice
      </Button>
    </Card>
  );
}
