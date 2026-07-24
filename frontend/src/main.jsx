// React entry point: mount the app into #root. App is the auth gate; the actual
// dashboard UI lives in CohortDashboard.
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
