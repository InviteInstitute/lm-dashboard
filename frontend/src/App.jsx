// Auth gate around the dashboard. On load it probes the session (/api/me): a live
// session renders the dashboard, otherwise the login screen. A dropped session
// (any 401, via the api interceptor) bounces back to login.
import React from 'react';
import api, { setOnUnauthorized } from './api';
import CohortDashboard from './CohortDashboard';
import Login from './Login';

const centered = {
  minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: '#0f1115', color: '#9aa4b2',
  fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
};
const logoutBtn = {
  position: 'fixed', bottom: 12, right: 12, zIndex: 9999,
  padding: '6px 10px', borderRadius: 8, border: '1px solid #2a2f3a',
  background: 'rgba(23,26,33,0.9)', color: '#9aa4b2', fontSize: 12, cursor: 'pointer',
  fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
};

export default function App() {
  const [status, setStatus] = React.useState('loading');  // 'loading' | 'out' | 'in'
  const [user, setUser] = React.useState(null);

  const check = React.useCallback(async () => {
    try {
      const { data } = await api.get('/api/me/');
      setUser(data);
      setStatus('in');
    } catch {
      setStatus('out');
    }
  }, []);

  React.useEffect(() => {
    setOnUnauthorized(() => setStatus('out'));
    check();
  }, [check]);

  const logout = async () => {
    try { await api.post('/api/logout/'); } catch { /* ignore */ }
    setUser(null);
    setStatus('out');
  };

  if (status === 'loading') return <div style={centered}>Loading…</div>;
  if (status === 'out') {
    return <Login onAuthed={(u) => { setUser(u); setStatus('in'); }} />;
  }
  return (
    <>
      <CohortDashboard />
      <button style={logoutBtn} onClick={logout}>
        Log out{user?.username ? ` · ${user.username}` : ''}
      </button>
    </>
  );
}
