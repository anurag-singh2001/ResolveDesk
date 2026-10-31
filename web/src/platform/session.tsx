import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { API_URL, ApiError } from "../api/client";

// The platform admin's token has its own key and its own fetch path. It is never sent by the
// tenant client and the tenant token is never sent here. A 401 or 403 clears it.
export const PLATFORM_KEY = "resolvedesk.platform.session";

interface Stored {
  token: string;
  expiresAt: string | null;
}

function read(): Stored | null {
  try {
    const raw = sessionStorage.getItem(PLATFORM_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Stored;
    if (!s.token) return null;
    if (s.expiresAt && new Date(s.expiresAt).getTime() <= Date.now()) return null;
    return s;
  } catch {
    return null;
  }
}

function write(s: Stored | null) {
  try {
    if (s) sessionStorage.setItem(PLATFORM_KEY, JSON.stringify(s));
    else sessionStorage.removeItem(PLATFORM_KEY);
  } catch {
    /* storage blocked: the in-memory token still works for this page */
  }
}

interface PlatformValue {
  signedIn: boolean;
  /** The server answered 404: the platform admin is not configured here. */
  disabled: boolean;
  notice: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  get: <T>(path: string) => Promise<T>;
}

const Ctx = createContext<PlatformValue | null>(null);

export function usePlatform(): PlatformValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePlatform outside PlatformProvider");
  return v;
}

async function call(path: string, init: RequestInit): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in (data as object) ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detail);
  }
  return data;
}

/** The API's 404 for "platform admin not configured" carries this exact detail. */
export const NOT_ENABLED_DETAIL = "platform admin not enabled";
const isOff = (e: ApiError) => e.detail === NOT_ENABLED_DETAIL;

export function PlatformProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState<Stored | null>(read);
  const [disabled, setDisabled] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const clear = useCallback((message: string | null) => {
    write(null);
    setStored(null);
    setNotice(message);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const out = (await call("/platform/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email, password }),
      })) as { access_token: string; expires_at: string | null };
      const s = { token: out.access_token, expiresAt: out.expires_at ?? null };
      write(s);
      setStored(s);
      setNotice(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && isOff(err)) setDisabled(true);
      throw err;
    }
  }, []);

  const token = stored?.token ?? null;
  const expiresAt = stored?.expiresAt ?? null;
  // A token that runs out while the page is open is dropped, not kept until the next 401.
  useEffect(() => {
    if (!token || !expiresAt) return;
    const ms = new Date(expiresAt).getTime() - Date.now();
    if (Number.isNaN(ms)) return;
    const id = window.setTimeout(() => clear("Your session has ended. Please sign in again."), Math.max(0, Math.min(ms, 2 ** 31 - 1)));
    return () => window.clearTimeout(id);
  }, [token, expiresAt, clear]);
  const get = useCallback(
    async <T,>(path: string): Promise<T> => {
      if (!token) throw new ApiError(401, "not authenticated");
      try {
        return (await call(`/platform${path}`, {
          headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
        })) as T;
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clear("Your session has ended. Please sign in again.");
        } else if (err instanceof ApiError && err.status === 404 && isOff(err)) {
          // Only the server's feature-off answer means "not enabled"; any other 404 is an error.
          clear(null);
          setDisabled(true);
        }
        throw err;
      }
    },
    [token, clear],
  );

  const value = useMemo<PlatformValue>(
    () => ({ signedIn: token !== null, disabled, notice, signIn, signOut: () => clear(null), get }),
    [token, disabled, notice, signIn, clear, get],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
