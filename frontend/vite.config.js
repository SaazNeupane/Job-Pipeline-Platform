import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Hosted architecture: frontend (Vercel) and backend (Render/FastAPI) are separate
// deployments, not same-origin -- api.js builds absolute URLs from VITE_API_BASE and relies
// on CORS (see backend/app/main.py's CORSMiddleware), not a same-origin /api proxy or a
// Flask static-file route serving this build's output. Default build output (dist/, right
// here in frontend/) rather than reaching into a sibling directory -- no dev-server proxy
// needed since api.js never uses relative /api paths.
export default defineConfig({
  plugins: [react()],
});
