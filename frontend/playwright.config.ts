import { defineConfig, devices } from '@playwright/test'
const liveURL = process.env.KATAAI_LIVE_E2E_URL
export default defineConfig({
  testDir: './e2e',
  fullyParallel: !liveURL,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: liveURL ?? 'http://127.0.0.1:8010', trace: 'retain-on-failure' },
  webServer: liveURL
    ? undefined
    : {
        command:
          'cd .. && KATAAI_API_PORT=8010 PYTHONPATH=backend:. .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010',
        url: 'http://127.0.0.1:8010/health',
        reuseExistingServer: false,
      },
  projects: liveURL
    ? [{ name: 'live-chromium', use: { ...devices['Desktop Chrome'] } }]
    : [
        { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
        { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
      ],
})
