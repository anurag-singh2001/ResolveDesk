import { useEffect, useRef, useState } from "react";

/**
 * Calls `tick` every `intervalMs` while `active`, for at most `maxMs` per active spell.
 * Returns true once it gave up, so the page can offer a manual refresh.
 */
export function usePolling(active: boolean, tick: () => unknown, intervalMs = 3000, maxMs = 120_000): boolean {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!active) {
      setTimedOut(false);
      return;
    }
    const started = Date.now();
    setTimedOut(false);
    const id = window.setInterval(() => {
      if (Date.now() - started >= maxMs) {
        window.clearInterval(id);
        setTimedOut(true);
        return;
      }
      void tickRef.current();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs, maxMs]);

  return timedOut;
}
