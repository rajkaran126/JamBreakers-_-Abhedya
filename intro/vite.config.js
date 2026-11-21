import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/intro/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1400 },
  server: { proxy: { '/api': 'http://localhost:8000', '/viewer': 'http://localhost:8000' } },
});
