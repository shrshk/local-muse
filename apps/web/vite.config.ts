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
      // Own service worker (src/sw.ts) so it can handle pushes; workbox injects the shell list.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      manifest: {
        name: 'Local Muse',
        short_name: 'Muse',
        description: 'Local-first personal agent',
        theme_color: '#111418',
        background_color: '#111418',
        display: 'standalone',
        id: '/',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      injectManifest: {
        // Shell only; API data is never cached (sw.ts routes navigations, nothing else).
        globPatterns: ['**/*.{js,css,html,svg,png}'],
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
