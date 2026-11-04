import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5179,
    strictPort: true,
    proxy: {
      // Speech bridge (speech/server.py).
      '/speech': { target: 'http://127.0.0.1:8089', rewrite: (path) => path.replace(/^\/speech/, '') },
    },
  },
});
