import { defineConfig } from "@playwright/test";

// E2E runs against a real, isolated backend (port 8100, throwaway e2e.db) and the Vite dev server (5174).
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:5174", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: "node e2e/start-backend.mjs",
      url: "http://localhost:8100/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_BASE_URL: "http://localhost:8100/api/v1" },
    },
  ],
});
