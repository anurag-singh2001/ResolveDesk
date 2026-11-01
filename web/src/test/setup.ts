import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Pages load lazily (S12.4): the first import of a page in a test file takes a few seconds.
configure({ asyncUtilTimeout: 15000 });

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// jsdom has no ResizeObserver; Recharts' ResponsiveContainer needs one (charts render empty here,
// so tests read the values from each chart's table view).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
