import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright integration test configuration
 * These tests run against the frontend with mocked API responses.
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Use 2 workers in CI for faster execution (GitHub Actions runners have 2-4 cores).
   * Use default (CPU cores) locally for maximum speed.
   */
  workers: process.env.CI ? 2 : undefined,
  /* Reporter to use */
  reporter: [['html', { open: 'never' }], ['list']],
  /* Shared settings for all the projects below */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://localhost:4000',
    /* Collect trace when retrying the failed test */
    trace: 'on-first-retry',
    /* Screenshot on failure */
    screenshot: 'only-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Uncomment to add more browsers
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: process.env.CI
    ? {
        // In CI, use production build for faster startup
        command: 'pnpm start',
        url: 'http://localhost:4000',
        reuseExistingServer: false,
        timeout: 120 * 1000,
        env: {
          PORT: '4000',
          NODE_ENV: 'production',
        },
      }
    : {
        // In local dev, use dev server (reuse if already running)
        command: 'pnpm dev',
        url: 'http://localhost:4000',
        reuseExistingServer: true,
        timeout: 120 * 1000,
      },
});
