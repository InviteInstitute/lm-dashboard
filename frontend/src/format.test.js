import { describe, it, expect } from 'vitest';
import { relTime, fmtDur, statusMeta } from './CohortDashboard.jsx';

describe('relTime', () => {
  it('shows a dash for missing input', () => {
    expect(relTime(null)).toBe('—');
  });
  it('renders seconds / minutes / hours / days by magnitude', () => {
    const ago = (s) => new Date(Date.now() - s * 1000).toISOString();
    expect(relTime(ago(10))).toBe('10s');
    expect(relTime(ago(120))).toBe('2m');
    expect(relTime(ago(7200))).toBe('2h');
    expect(relTime(ago(2 * 86400))).toBe('2d');
  });
  it('never goes negative for a future timestamp', () => {
    expect(relTime(new Date(Date.now() + 60000).toISOString())).toBe('0s');
  });
});

describe('fmtDur', () => {
  it('shows a dash for null', () => {
    expect(fmtDur(null)).toBe('—');
  });
  it('formats seconds, minutes, hours with one decimal', () => {
    expect(fmtDur(5)).toBe('5.0s');
    expect(fmtDur(90)).toBe('1.5m');
    expect(fmtDur(5400)).toBe('1.5h');
  });
});

describe('statusMeta', () => {
  it('uses the active trigger as the headline', () => {
    expect(statusMeta('wheel_spin', true).label).toBe('Wheel-spinning');
    expect(statusMeta('explorer', true).label).toBe('Explorer');
  });
  it('is OK when there is data but no active trigger', () => {
    expect(statusMeta(null, true).label).toBe('OK');
  });
  it('is No data when the student has no materialized state', () => {
    expect(statusMeta(null, false).label).toBe('No data');
  });
});
