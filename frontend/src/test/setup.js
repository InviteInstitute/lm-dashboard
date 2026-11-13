import "@testing-library/jest-dom";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom has no real object-URL machinery; stub it so the export download path
// (createObjectURL -> click -> revokeObjectURL) runs without throwing.
window.URL.createObjectURL = vi.fn(() => "blob:mock");
window.URL.revokeObjectURL = vi.fn(() => {});

// Unmount React trees and clear mock call history after every test.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// jsdom has no native dialog lifecycle; browser checks cover focus and Escape.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};

// jsdom has no ResizeObserver; Carbon's components observe their own size.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
