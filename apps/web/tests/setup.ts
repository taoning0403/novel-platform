import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

class MockResizeObserver {
  observe() {
    // Layout is not calculated by jsdom.
  }

  unobserve() {
    // Layout is not calculated by jsdom.
  }

  disconnect() {
    // Layout is not calculated by jsdom.
  }
}

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: MockResizeObserver,
});

const jsdomGetComputedStyle = window.getComputedStyle;
Object.defineProperty(window, "getComputedStyle", {
  writable: true,
  value: (element: Element) => jsdomGetComputedStyle(element),
});

afterEach(() => cleanup());
