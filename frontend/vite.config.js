import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Single Render deploy: FastAPI serves this build's dist/ directly (StaticFiles mount +
// SPA-fallback route in backend/app/main.py), one origin, no CORS in production. Default
// build output (dist/, right here in frontend/) rather than reaching into a sibling
// directory. Locally, the Vite dev server and backend still run on separate ports, so
// api.js builds absolute URLs from VITE_API_BASE and relies on CORS there.
export default defineConfig({
  plugins: [react()],
});
