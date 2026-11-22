import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En developpement, l'API est atteinte par le meme domaine que l'interface (proxy) : le cookie de
// session est en SameSite=Strict, il ne partirait pas vers un autre domaine.
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.PORT ?? 5173),
    proxy: { "/api": process.env.API_CIBLE ?? "http://localhost:8000" },
  },
});
