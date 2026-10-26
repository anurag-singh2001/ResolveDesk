import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { configureClient } from "../api/client";
import { api } from "../api/endpoints";
import type { Business, Me } from "../api/types";

// Token lives in memory and sessionStorage (never localStorage, per the contract): it survives
// a reload of this tab but not a new tab or a closed browser.
const STORAGE_KEY = "resolvedesk.session";
export const SESSION_ENDED = "Your session has ended. Please sign in again.";

interface Stored {
  token: string;
  expiresAt: string | null;
  tenant: string;
  businessName: string | null;
}

function readStored(): Stored | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Stored;
    if (!s.token) return null;
    if (s.expiresAt && new Date(s.expiresAt).getTime() <= Date.now()) return null;
    return s;
  } catch {
    return null;
  }
}

function writeStored(s: Stored | null) {
  try {
    if (s) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked: the in-memory token still works for this page */
  }
}

type Status = "loading" | "signed_out" | "signed_in";

interface AuthValue {
  status: Status;
  me: Me | null;
  businessName: string;
  /** Shown on the login page after a 401 ("Your session has ended"). */
  notice: string | null;
  /** True after the user signed out themselves: the next sign-in (maybe another person) starts
   * on their home page, not on the page the last user had open. */
  signedOutByUser: boolean;
  signIn: (tenant: string, email: string, password: string, business?: Business) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const initial = useRef<Stored | null>(readStored());
  const tokenRef = useRef<string | null>(initial.current?.token ?? null);
  const [stored, setStored] = useState<Stored | null>(initial.current);
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status>(initial.current ? "loading" : "signed_out");
  const [notice, setNotice] = useState<string | null>(null);
  const [signedOutByUser, setSignedOutByUser] = useState(false);

  const clear = useCallback((why: string | null, byUser = false) => {
    tokenRef.current = null;
    writeStored(null);
    setStored(null);
    setMe(null);
    setStatus("signed_out");
    setNotice(why);
    setSignedOutByUser(byUser);
  }, []);

  useEffect(() => {
    configureClient({
      getToken: () => tokenRef.current,
      onUnauthorized: () => {
        if (tokenRef.current) clear(SESSION_ENDED);
      },
    });
  }, [clear]);

  // Restore a session from this tab's storage.
  useEffect(() => {
    if (!initial.current) return;
    let cancelled = false;
    api
      .me()
      .then((m) => {
        if (!cancelled) {
          setMe(m);
          setStatus("signed_in");
        }
      })
      .catch(() => {
        if (!cancelled && tokenRef.current) clear(SESSION_ENDED);
      });
    return () => {
      cancelled = true;
    };
  }, [clear]);

  // End the session at expires_at even if no request is made.
  useEffect(() => {
    if (!stored?.expiresAt) return;
    const ms = new Date(stored.expiresAt).getTime() - Date.now();
    if (ms <= 0) return;
    const t = window.setTimeout(() => clear(SESSION_ENDED), Math.min(ms, 2 ** 31 - 1));
    return () => window.clearTimeout(t);
  }, [stored, clear]);

  const signIn = useCallback(
    async (tenant: string, email: string, password: string, business?: Business) => {
      const res = await api.login(tenant, email, password);
      tokenRef.current = res.access_token;
      try {
        const m = await api.me();
        const s: Stored = {
          token: res.access_token,
          expiresAt: res.expires_at ?? null,
          tenant,
          businessName: m.tenant?.name ?? business?.name ?? null,
        };
        writeStored(s);
        setStored(s);
        setMe(m);
        setNotice(null);
        setSignedOutByUser(false);
        setStatus("signed_in");
      } catch (err) {
        tokenRef.current = null;
        throw err;
      }
    },
    [],
  );

  const signOut = useCallback(() => clear(null, true), [clear]);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      me,
      businessName: me?.tenant?.name ?? stored?.businessName ?? stored?.tenant ?? "",
      notice,
      signedOutByUser,
      signIn,
      signOut,
    }),
    [status, me, stored, notice, signedOutByUser, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
