import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_KEY, ThemeProvider, ThemeSwitcher } from "./theme";

type Listener = (e: { matches: boolean }) => void;
let listeners: Listener[] = [];
let systemDark = true;

function mockMatchMedia(dark: boolean) {
  systemDark = dark;
  listeners = [];
  window.matchMedia = vi.fn().mockImplementation(() => ({
    get matches() {
      return systemDark;
    },
    addEventListener: (_: string, l: Listener) => listeners.push(l),
    removeEventListener: (_: string, l: Listener) => {
      listeners = listeners.filter((x) => x !== l);
    },
  })) as unknown as typeof window.matchMedia;
}
function osChange(dark: boolean) {
  systemDark = dark;
  act(() => listeners.forEach((l) => l({ matches: dark })));
}
const isDark = () => document.documentElement.classList.contains("dark");
const ui = (
  <ThemeProvider>
    <ThemeSwitcher />
  </ThemeProvider>
);

describe("ThemeSwitcher", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });
  afterEach(() => {
    // @ts-expect-error remove the mock between tests
    delete window.matchMedia;
  });

  it("defaults to system and follows the browser setting (dark and light)", () => {
    mockMatchMedia(true);
    const first = render(ui);
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true");
    expect(isDark()).toBe(true);
    first.unmount();
    mockMatchMedia(false);
    render(ui);
    expect(isDark()).toBe(false);
  });

  it("flips live on a browser change while on system, and removes its listener on unmount", () => {
    mockMatchMedia(true);
    const { unmount } = render(ui);
    osChange(false);
    expect(isDark()).toBe(false);
    osChange(true);
    expect(isDark()).toBe(true);
    unmount();
    expect(listeners).toHaveLength(0);
  });

  it("ignores browser changes after an explicit choice, persists it, and keeps it after a reload", async () => {
    mockMatchMedia(true);
    const user = userEvent.setup();
    const first = render(ui);
    await user.click(screen.getByRole("button", { name: "Light" }));
    expect(isDark()).toBe(false);
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
    osChange(true);
    expect(isDark()).toBe(false);
    first.unmount();

    document.documentElement.classList.remove("dark");
    render(ui); // reload
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
    expect(isDark()).toBe(false);

    await user.click(screen.getByRole("button", { name: "Dark" }));
    expect(isDark()).toBe(true);
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("treats an invalid stored value as system", () => {
    mockMatchMedia(false);
    localStorage.setItem(THEME_KEY, "purple");
    render(ui);
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true");
    expect(isDark()).toBe(false);
  });
});
