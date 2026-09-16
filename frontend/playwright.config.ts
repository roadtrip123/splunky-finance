import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: [
    {
      command:
        "../backend/.venv/bin/uvicorn --app-dir ../scripts browser_backend:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/ready",
      reuseExistingServer: false,
    },
    {
      command: "npm run start",
      url: "http://localhost:3000",
      reuseExistingServer: false,
      env: {
        BACKEND_URL: "http://127.0.0.1:8001",
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
