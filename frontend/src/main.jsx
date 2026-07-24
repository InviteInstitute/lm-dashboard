// React entry point: mount the dashboard into #root. Auth is handled by the
// browser's native Basic-Auth dialog (the whole origin is gated server-side), so
// there's no in-app login screen -- the SPA only loads once the browser is
// authenticated.
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import CohortDashboard from './CohortDashboard';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <CohortDashboard />
  </React.StrictMode>
);
