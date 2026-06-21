// React entry point: mount the dashboard into #root. All the UI lives in
// CohortDashboard; this file just bootstraps it.
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import CohortDashboard from './CohortDashboard';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <CohortDashboard />
  </React.StrictMode>
);
