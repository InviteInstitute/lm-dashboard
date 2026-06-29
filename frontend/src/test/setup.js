import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom doesn't implement these; the dashboard uses them for reset/export.
window.confirm = vi.fn(() => true);
window.alert = vi.fn(() => {});
// jsdom has no real object-URL machinery; stub it so the export download path
// (createObjectURL -> click -> revokeObjectURL) runs without throwing.
window.URL.createObjectURL = vi.fn(() => 'blob:mock');
window.URL.revokeObjectURL = vi.fn(() => {});

// Unmount React trees and clear mock call history after every test.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
