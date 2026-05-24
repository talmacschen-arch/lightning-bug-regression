import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  reporter: [['html', { open: 'never' }], ['line']],
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    // M5-1 PR #94 lesson (§14 R32): on e2e failure, log alone can't
    // diagnose layout / responsive / mount-race issues. Retain
    // trace + screenshot so CI artifacts (uploaded via ci-gate.yml)
    // carry diagnosable evidence.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    port: 5173,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
