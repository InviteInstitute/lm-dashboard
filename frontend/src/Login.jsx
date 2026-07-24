// The login screen. Everyone signs in here (a shared credential is fine); the
// browser's persistent board id (from api.boardId) rides along so the server
// binds this session to its own isolated board.
import React from 'react';
import api, { boardId } from './api';

const wrap = {
  minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: '#0f1115', color: '#e6e6e6',
  fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
};
const card = {
  width: 320, padding: 28, borderRadius: 12, background: '#171a21',
  border: '1px solid #2a2f3a', boxShadow: '0 8px 30px rgba(0,0,0,0.4)',
};
const label = { display: 'block', fontSize: 12, color: '#9aa4b2', margin: '14px 0 6px' };
const input = {
  width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: 8,
  border: '1px solid #2a2f3a', background: '#0f1115', color: '#e6e6e6', fontSize: 14,
};
const button = {
  width: '100%', marginTop: 20, padding: '10px 12px', borderRadius: 8, border: 0,
  background: '#3b82f6', color: 'white', fontSize: 14, fontWeight: 600, cursor: 'pointer',
};

export default function Login({ onAuthed }) {
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post('/api/login/', {
        username, password, board_id: boardId(),
      });
      onAuthed(data);
    } catch (err) {
      setError(err.response?.status === 401
        ? 'Invalid username or password'
        : 'Login failed — is the server up?');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={wrap}>
      <form style={card} onSubmit={submit}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Learner Modeling Dashboard</div>
        <div style={{ fontSize: 12, color: '#9aa4b2', marginTop: 4 }}>Sign in to your board</div>

        <label style={label} htmlFor="username">Username</label>
        <input id="username" style={input} value={username} autoFocus
               autoComplete="username"
               onChange={(e) => setUsername(e.target.value)} />

        <label style={label} htmlFor="password">Password</label>
        <input id="password" style={input} type="password" value={password}
               autoComplete="current-password"
               onChange={(e) => setPassword(e.target.value)} />

        {error && <div style={{ color: '#f87171', fontSize: 13, marginTop: 12 }}>{error}</div>}

        <button style={{ ...button, opacity: busy ? 0.6 : 1 }} type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
