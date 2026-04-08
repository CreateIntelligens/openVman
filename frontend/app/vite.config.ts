import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@contracts': path.resolve(__dirname, '../../contracts'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8200',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8200',
        ws: true,
      },
    },
  },
});
