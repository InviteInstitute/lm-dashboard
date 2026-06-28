// Shared axios instance for every call to the read API. Import this rather than
// hitting the server directly so the base URL and headers stay in one place.
import axios from 'axios';

// Base URL of the FastAPI read API. Defaults to the local server for `npm run
// dev`. Set VITE_API_URL='' for the remote build so calls go to the SAME origin
// that served the page (FastAPI serves the built app behind the Cloudflare
// tunnel: one host, no CORS). `??` not `||` so an empty string is honored as
// "relative" instead of falling back to localhost.
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  // 'ngrok-skip-browser-warning' tells ngrok's free tier to skip its interstitial
  // HTML page for these calls (otherwise the API would get that page instead of
  // JSON). Any custom header triggers the skip; it's harmless off ngrok.
  headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true' },
});

export default api;
