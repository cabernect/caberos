import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import path from "path";

// Read package.json rather than importing it. Import attributes
// (`with { type: "json" }`) are a hard syntax error on Node < 22, and the repo
// does not pin a Node version, so a contributor on an older runtime would get
// an unexplained parse failure in the config itself.
const pkg = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as { version: string };

const config = {
  plugins: [react(), tailwindcss()],
  // The dashboard ships inside the desktop shell, so its version *is* the shell
  // version. Exposing it lets the UI compare against the gateway's reported
  // version and catch an update that replaced the shell but not the bundled
  // gateway — a documented Tauri NSIS failure mode for bundled sidecars.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    globals: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8081",
        changeOrigin: true,
        cookieDomainRewrite: "",
      },
      "/health": {
        target: "http://127.0.0.1:8081",
        changeOrigin: true,
      },
    },
  },
};

export default config;
