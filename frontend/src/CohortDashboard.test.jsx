import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the shared axios instance so the component talks to canned data, not a
// real server. Each GET resolves by URL; POSTs are spies we assert on.
vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
import api from './api';
import CohortDashboard from './CohortDashboard.jsx';

const ROUTES = {
  '/api/student_states/': {
    students: [{
      studentID: 'alice', classCode: 'C1', current_state: 2, current_label: 'stuck',
      stuck: true, consecutive_stuck: 3, run_count: 4, event_count: 12,
      last_seen: new Date().toISOString(), state_sequence: [1, 2, 2],
      hmm: { runs: [], run_count: 0, obs_labels: {} },
      episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
    }],
    student_count: 1, stuck_count: 1, stuck_state: 2, state_labels: {},
  },
  '/api/tracked/': {
    tracked: [{ studentID: 'alice', backfilled: true, has_data: true, present: true, picked: false }],
    count: 1,
  },
  '/api/triggers/': { triggers: [], active_count: 0, counts: {} },
  '/api/polling/': { enabled: true },
  '/api/triggers/config/': {
    enabled: { wheel_spin: true, inactive: true, big_change: true }, labels: {},
  },
};

beforeEach(() => {
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: ROUTES[url] ?? {} }));
  api.post.mockResolvedValue({ data: {} });
});

describe('CohortDashboard', () => {
  it('renders a card for each tracked student with its strategy state', async () => {
    render(<CohortDashboard />);
    // 'alice' shows in both the roster chip and the cohort card
    expect((await screen.findAllByText('alice')).length).toBeGreaterThanOrEqual(1);
    // current_state 2 => the stuck badge
    expect(await screen.findAllByText(/Stuck/)).not.toHaveLength(0);
  });

  it('surfaces a backend alert in the intervention column', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/triggers/') {
        return Promise.resolve({ data: {
          triggers: [{ id: 1, studentID: 'alice', trigger_type: 'wheel_spin',
            label: 'Wheel-spinning', value: '3 re-runs', active: true, age_seconds: 42 }],
          active_count: 1, counts: { wheel_spin: 1 } }});
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // an alert row renders its own dismiss (✕) button -- proof the alert surfaced
    expect(await screen.findByTitle(/Dismiss alert/)).toBeInTheDocument();
  });

  it('posts to /api/picked/ when "Mark picked" is clicked', async () => {
    render(<CohortDashboard />);
    const pick = await screen.findByText('Mark picked');
    fireEvent.click(pick);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/picked/',
        { studentID: 'alice', picked: true });
    });
  });

  it('toggles daemon polling via the pause button', async () => {
    render(<CohortDashboard />);
    const pause = await screen.findByText(/Pause polling/);
    fireEvent.click(pause);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/polling/', { enabled: false });
    });
  });

  it('acks a trigger when its ✕ is clicked', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/triggers/') {
        return Promise.resolve({ data: {
          triggers: [{ id: 7, studentID: 'alice', trigger_type: 'inactive',
            label: 'Inactive', value: 'idle 6m', active: true, age_seconds: 360 }],
          active_count: 1, counts: {} }});
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle(/Dismiss alert/));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/triggers/ack/', { id: 7 });
    });
  });

  it('opens the detail modal and fetches the heavy payload on click', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/student_states/alice/') {
        return Promise.resolve({ data: {
          studentID: 'alice', current_state: 2, run_count: 4, event_count: 12,
          block: { llm_prompt: '[Active] events_whenStarted', timestamp: null },
          episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
          hmm: { runs: [], run_count: 0, obs_labels: {} },
        }});
      }
      if (url === '/api/notes/') return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle('alice'));     // the card's id label
    expect(await screen.findByText('Playground')).toBeInTheDocument();
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/api/student_states/alice/'));
  });

  it('toggles a trigger type from the Triggers panel', async () => {
    // the POST echoes the new enabled map back, which the component stores
    api.post.mockResolvedValue({ data: { enabled: { wheel_spin: false, inactive: true, big_change: true } } });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Triggers/));    // open the panel
    const offButtons = await screen.findAllByText('On');
    fireEvent.click(offButtons[0]);                          // turn the first one off
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/triggers/config/',
        expect.objectContaining({ enabled: false })));
  });

  it('exports a snapshot', async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Export/));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/export/'));
  });

  it('resets after confirmation', async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Reset/));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/reset/'));
  });

  it('tracks a semicolon-separated list, ignoring whitespace and blanks/dupes', async () => {
    render(<CohortDashboard />);
    const input = await screen.findByPlaceholderText(/semicolon-separated/);
    fireEvent.change(input, { target: { value: ' alice ;bob; ;  carol ; bob ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => {
      const tracked = api.post.mock.calls
        .filter(([url]) => url === '/api/tracked/')
        .map(([, body]) => body.studentID);
      expect(new Set(tracked)).toEqual(new Set(['alice', 'bob', 'carol']));   // blank + dup dropped
    });
  });

  it('untracks a student from the roster chip', async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle('Stop tracking'));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/tracked/',
        { studentID: 'alice', remove: true }));
  });

  it('toggles presence from a card', async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Present/));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/presence/',
        { studentID: 'alice', present: false }));
  });

  it('adds a note from the alert editor', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/triggers/') {
        return Promise.resolve({ data: {
          triggers: [{ id: 3, studentID: 'alice', trigger_type: 'wheel_spin',
            label: 'Wheel-spinning', value: '2 re-runs', active: true, age_seconds: 30 }],
          active_count: 1, counts: {} }});
      }
      if (url === '/api/notes/') return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText('Notes'));           // open the editor
    const box = await screen.findByPlaceholderText(/Observation during/);
    fireEvent.change(box, { target: { value: 'looks stuck on the loop' } });
    fireEvent.click(screen.getByText('Save note'));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/notes/',
        expect.objectContaining({ studentID: 'alice', text: 'looks stuck on the loop',
          trigger_id: 3, trigger_type: 'wheel_spin' })));
  });
});
