import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "e2e", timeout: 30000, fullyParallel: true,
  use: { baseURL: "http://127.0.0.1:8124", browserName: "chromium", viewport: { width: 1280, height: 920 } },
  webServer: { command: "npm run preview", url: "http://127.0.0.1:8124", reuseExistingServer: !process.env.CI },
});
