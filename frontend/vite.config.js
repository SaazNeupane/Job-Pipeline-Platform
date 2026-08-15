import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output lands directly in webapp/static/dist -- app.py's SPA route
// serves it from there, and it's committed to the repo so run_webapp.bat
// users never need Node installed. The dev server proxies /api to Flask
// (python -m webapp.app, port 5000) so `npm run dev` works against real
// data without CORS configuration.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../webapp/static/dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:5000",
    },
  },
});
