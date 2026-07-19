// API configuration.
// To connect a Google Apps Script backend later:
// 1. Deploy your Apps Script Web App (doPost) and copy the /exec URL.
// 2. Set REACT_APP_APPS_SCRIPT_URL=<your-url> in /app/frontend/.env
// 3. Restart the frontend. No component code needs to change.
//
// While REACT_APP_APPS_SCRIPT_URL is empty, all API calls are served from
// src/api/local-adapter.js which reads from src/data/*.js (dummy JSON).

export const APPS_SCRIPT_URL = process.env.REACT_APP_APPS_SCRIPT_URL || '';
export const USE_MOCK = !APPS_SCRIPT_URL;
export const MOCK_DELAY_MS = 40; // small delay so loading states are exercised
