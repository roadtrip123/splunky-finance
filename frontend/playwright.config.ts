import { defineConfig, devices } from "@playwright/test";
const port = Number(process.env.BROWSER_TEST_PORT || 3000);
const backendPort = Number(process.env.BROWSER_TEST_BACKEND_PORT || 8001);
const baseURL = `http://localhost:${port}`;
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: [
    {
      command: `../backend/.venv/bin/uvicorn --app-dir ../scripts browser_backend:app --host 127.0.0.1 --port ${backendPort}`,
      url: `http://127.0.0.1:${backendPort}/ready`,
      env: { APP_ORIGIN: baseURL },
      reuseExistingServer: false,
    },
    {
      command: `npm run start -- --port ${port}`,
      url: baseURL,
      reuseExistingServer: false,
      env: {
        BACKEND_URL: `http://127.0.0.1:${backendPort}`,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
