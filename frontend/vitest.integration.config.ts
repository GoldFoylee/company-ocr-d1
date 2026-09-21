import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    fileParallelism: false,
    include: ['src/**/*.integration.test.{ts,tsx}'],
    setupFiles: './src/setupTests.ts',
  },
})
