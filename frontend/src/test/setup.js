import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom doesn't implement these; the dashboard uses them for reset/export.
window.confirm = vi.fn(() => true);
window.alert = vi.fn(() => {});

// Unmount React trees and clear mock call history after every test.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
