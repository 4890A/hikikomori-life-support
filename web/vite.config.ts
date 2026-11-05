import { defineConfig } from 'vite';

const shared = {
  port: 5179,
  strictPort: true,
  proxy: {
    // Speech bridge (speech/server.py).
    '/speech': { target: 'http://127.0.0.1:8089', rewrite: (path: string) => path.replace(/^\/speech/, '') },
  },
};

export default defineConfig({ server: shared, preview: shared });
