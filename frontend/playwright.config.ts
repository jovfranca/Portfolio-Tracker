import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:8001', channel: 'msedge', headless: true,
    extraHTTPHeaders: { 'X-Aurion-Request': '1' } },
})
