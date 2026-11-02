import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

/** What the person chose. "system" follows the browser or OS and is the default. */
export type ThemePreference = "system" | "light" | "dark";
/** What is actually applied. */
export type Theme = "dark" | "light";
export const THEME_KEY = "resolvedesk.theme";
const QUERY = "(prefers-color-scheme: dark)";

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // Storage can be blocked; fall through to the default.
  }
  return "system";
}

function systemTheme(): Theme {
  // Without matchMedia (old browsers, tests) the dark-first default applies.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia(QUERY).matches ? "dark" : "light";
}

interface ThemeCtx {
  preference: ThemePreference;
  theme: Theme;
  setPreference: (p: ThemePreference) => void;
}

const Ctx = createContext<ThemeCtx>({ preference: "system", theme: "dark", setPreference: () => {} });

export function useTheme(): ThemeCtx {
  return useContext(Ctx);
}

/** The class lives on <html> and is the single switch Tailwind reads; index.html sets it before paint. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const theme: Theme = preference === "system" ? system : preference;

  // Follow the browser setting live; the listener is removed on unmount.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setSystem(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const setPreference = useCallback((p: ThemePreference) => {
    setPreferenceState(p);
    try {
      localStorage.setItem(THEME_KEY, p);
    } catch {
      // Not persisted; the choice still applies for this visit.
    }
  }, []);

  const value = useMemo(() => ({ preference, theme, setPreference }), [preference, theme, setPreference]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const OPTIONS: Array<[ThemePreference, string]> = [
  ["system", "System"],
  ["light", "Light"],
  ["dark", "Dark"],
];

/** Segmented control. The active segment is the one allowed orange fill (dark brown in dark). */
export function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  const index = OPTIONS.findIndex(([v]) => v === preference);
  const [, current] = OPTIONS[index < 0 ? 0 : index];
  const [nextValue] = OPTIONS[(index + 1) % OPTIONS.length];
  return (
    <>
      {/* Phone: one small button that cycles System, Light, Dark, so the header stays uncrowded. */}
      <button
        type="button"
        aria-label={`Change theme, now ${current}`}
        onClick={() => setPreference(nextValue)}
        className="inline-flex h-8 items-center rounded-md border border-border px-2 text-xs font-medium text-foreground transition-colors duration-200 hover:bg-muted sm:hidden"
      >
        {current}
      </button>
    <div role="group" aria-label="Theme" className="hidden rounded-md border border-border p-0.5 sm:inline-flex">
      {OPTIONS.map(([value, label]) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => setPreference(value)}
            className={
              "rounded px-2 py-1 text-xs font-medium transition-colors duration-200 " +
              (active
                ? "bg-orange-100 text-orange-900 dark:bg-orange-900/40 dark:text-orange-100"
                : "text-muted-foreground hover:text-foreground")
            }
          >
            {label}
          </button>
        );
      })}
    </div>
    </>
  );
}
