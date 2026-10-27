// The only place the app talks HTTP. Adds the bearer token, parses JSON, turns non-2xx into
// ApiError, and reports a 401 on an authenticated call so the session can end.

export const API_URL: string = (
  (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type TokenGetter = () => string | null;
type UnauthorizedHandler = () => void;

let getToken: TokenGetter = () => null;
let onUnauthorized: UnauthorizedHandler = () => {};

/** Wired once by the AuthProvider. */
export function configureClient(opts: { getToken: TokenGetter; onUnauthorized: UnauthorizedHandler }) {
  getToken = opts.getToken;
  onUnauthorized = opts.onUnauthorized;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  /** Public endpoints (login, businesses): no token, and a 401 is a normal answer. */
  anonymous?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = opts.anonymous ? null : getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error)?.name === "AbortError") throw err;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  if (res.status === 401 && !opts.anonymous) {
    onUnauthorized();
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
    const detail =
      data && typeof data === "object" && "detail" in (data as object)
        ? (data as { detail: unknown }).detail
        : data;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

/** A human sentence for an error we have no specific copy for. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return err.message;
    if (err.status === 404) return "We couldn't find that. It may not exist or you may not have access.";
    if (err.status === 403) return "You don't have permission to do that.";
    if (err.status >= 500) return "Something went wrong on our side. Please try again.";
    if (Array.isArray(err.detail)) {
      return err.detail
        .map((d) => (typeof d === "string" ? d : (d as { msg?: string })?.msg ?? ""))
        .filter(Boolean)
        .join(" ");
    }
    if (typeof err.detail === "string") return err.detail;
    return `Request failed (${err.status}).`;
  }
  return "Something went wrong. Please try again.";
}
