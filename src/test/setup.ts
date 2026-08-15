// Global test setup, loaded by vitest before any test file.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Testing Library only auto-cleans when it detects a global afterEach, which it
// does not with vitest's `globals: true` in every version. Unmounting explicitly
// keeps one test's DOM from leaking into the next.
afterEach(() => {
  cleanup();
});

// jsdom implements no layout and no pointer capture, so a handful of DOM methods
// the real components call simply do not exist there. Without these stubs the
// failures are unrelated to the behaviour under test: the scroll wheel throws on
// mount calling scrollTo, and Radix's popover and dialog throw on open.
//
// These are deliberately no-ops rather than fakes. Nothing here should be used to
// assert against — a test that needs real layout is a test jsdom cannot run, and
// belongs in an end-to-end suite instead.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = vi.fn();
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = vi.fn();
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = vi.fn();
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!globalThis.matchMedia) {
  globalThis.matchMedia = vi.fn((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof globalThis.matchMedia;
}
