import { test as base, expect } from '@playwright/test'

export const test = base.extend<{ authenticated: void }>({
  authenticated: [async ({ context, request }, use) => {
    const credentials = { username: 'local', token: process.env.DEV_AUTH_TOKEN ?? 'browser-test-only' }
    for (const client of [context.request, request]) {
      const response = await client.post('/api/auth/dev', { data: credentials })
      expect(response.ok(), 'Start the dedicated browser API with development auth enabled').toBeTruthy()
    }
    await use()
  }, { auto: true }],
})
export { expect }
