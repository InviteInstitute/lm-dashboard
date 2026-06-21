// Shared axios instance for every call to the read API. Import this rather than
// hitting the server directly so the base URL and headers stay in one place.
import axios from 'axios';

// Base URL of the FastAPI read API. Defaults to the local server; override it at
// build time with the VITE_API_URL environment variable.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

export default api;
