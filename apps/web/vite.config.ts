import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

// In `npm run dev`, API and realtime go to the Compose web container, same as production.
const STACK = process.env.LOCAL_MUSE_URL ?? 'http://localhost:8080';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Local Muse',
        short_name: 'Muse',
        description: 'Local-first personal agent',
        theme_color: '#111418',
        background_color: '#111418',
        display: 'standalone',
        icons: [{ src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
      workbox: {
        // Shell caching only; API data is never served from cache.
        navigateFallbackDenylist: [/^\/api\//, /^\/connection\//],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': STACK,
      '/connection': { target: STACK.replace(/^http/, 'ws'), ws: true },
    },
  },
});
