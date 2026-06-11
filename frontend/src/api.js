import axios from 'axios';

// The FastAPI server. Override at build time with VITE_API_URL if needed.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

export default api;
