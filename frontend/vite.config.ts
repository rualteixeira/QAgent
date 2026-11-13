import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Porta 5173 = origem permitida no CORS da API (QAGENT_CORS_ORIGINS).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
});
