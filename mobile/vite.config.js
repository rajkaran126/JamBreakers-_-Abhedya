import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readdirSync, statSync, writeFileSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

// Writes dist/sw.js with the exact list of built files, so the app shell is cached for offline use.
function serviceWorker() {
  return {
    name: 'aegis-sw',
    apply: 'build',
    closeBundle() {
      const dist = 'dist', files = [];
      const walk = (d) => readdirSync(d).forEach((f) => { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : files.push(p); });
      walk(dist);
      const urls = ['./', ...files.map((f) => './' + relative(dist, f).split('\\').join('/')).filter((u) => u !== './sw.js')];
      const version = Date.now().toString(36);
      const src = readFileSync('sw.template.js', 'utf8').replace('__VERSION__', version).replace('__FILES__', JSON.stringify(urls));
      writeFileSync(join(dist, 'sw.js'), src);
    },
  };
}

export default defineConfig({
  base: '/app/',
  plugins: [react(), serviceWorker()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 600 },
  server: { proxy: { '/ws': { target: 'ws://localhost:8000', ws: true }, '/api': 'http://localhost:8000' } },
});
