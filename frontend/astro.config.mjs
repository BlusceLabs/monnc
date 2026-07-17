import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';
import node from '@astrojs/node';

// Server-rendered so every TMDB endpoint can be queried per-request
// (search, discover, pagination, dynamic detail pages, etc.).
export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  integrations: [svelte()],
  server: { port: 4321, host: true },
  vite: {
    ssr: { noExternal: ['svelte'] },
  },
});
