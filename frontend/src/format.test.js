import { describe, it, expect } from 'vitest';
import { relTime, fmtDur, stateMeta } from './CohortDashboard.jsx';

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

describe('stateMeta', () => {
  it('falls back to NOSTATE when there is no state', () => {
    expect(stateMeta(null).label).toBe('No runs yet');
    expect(stateMeta({ current_state: null }).label).toBe('No runs yet');
  });
  it('maps the three HMM states to labels', () => {
    expect(stateMeta({ current_state: 0 }).label).toBe('Iterator');
    expect(stateMeta({ current_state: 1 }).label).toBe('Explorer');
    expect(stateMeta({ current_state: 2 }).label).toBe('Stuck');
  });
  it('falls back for an unknown state value', () => {
    expect(stateMeta({ current_state: 99 }).label).toBe('No runs yet');
  });
});
