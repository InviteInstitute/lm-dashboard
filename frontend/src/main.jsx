// React entry point: mount the dashboard into #root. There's no login screen --
// the dashboard is public, gated only against bots by Cloudflare Turnstile
// (TurnstileGate renders its full-screen challenge on top of everything else
// the moment the API first 403s a request; see api.js and TurnstileGate.jsx).
import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import CohortDashboard from "./CohortDashboard";
import TurnstileGate from "./TurnstileGate";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <TurnstileGate />
    <CohortDashboard />
  </React.StrictMode>,
);
