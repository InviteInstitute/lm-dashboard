import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the shared api module (default axios instance + the auth helpers).
vi.mock('./api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  setOnUnauthorized: vi.fn(),
  boardId: () => 'test-board',
  API_URL: '',
}));
import api from './api';
import App from './App.jsx';

// After a successful login the dashboard mounts and fires its own reads; hand
// back empty-but-shaped data so it renders without throwing.
const dashboardData = { students: [], tracked: [], triggers: [], switches: [], notes: [], enabled: {} };

beforeEach(() => { vi.clearAllMocks(); });

describe('App auth gate', () => {
  it('shows the login screen when the session probe is unauthorized', async () => {
    api.get.mockRejectedValue({ response: { status: 401 } });
    render(<App />);
    expect(await screen.findByText('Sign in to your board')).toBeInTheDocument();
  });

  it('sends username, password, and the browser board id on login', async () => {
    api.get.mockImplementation((url) =>
      url === '/api/me/'
        ? Promise.reject({ response: { status: 401 } })
        : Promise.resolve({ data: dashboardData }));
    api.post.mockResolvedValueOnce({ data: { id: 1, username: 'demo' } });

    render(<App />);
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/login/',
      { username: 'demo', password: 'pw', board_id: 'test-board' },
    ));
  });

  it('shows an error message on a bad login', async () => {
    api.get.mockRejectedValue({ response: { status: 401 } });
    api.post.mockRejectedValue({ response: { status: 401 } });
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/invalid username or password/i)).toBeInTheDocument();
  });
});
