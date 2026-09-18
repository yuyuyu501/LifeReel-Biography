import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
  const env = loadEnv(mode, repositoryRoot, "");
  const apiAccessKey = process.env.API_ACCESS_KEY || env.API_ACCESS_KEY;

  return {
    envDir: repositoryRoot,
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    build: {
      rollupOptions: {
        output: { manualChunks: { "ui-vendor": ["radix-ui"] } },
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/v1": {
          target: env.VITE_DEV_API_TARGET || "http://localhost:8000",
          changeOrigin: true,
          ws: true,
          headers: apiAccessKey ? { "X-API-Key": apiAccessKey } : undefined,
        },
        "/health": {
          target: env.VITE_DEV_API_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      globals: true,
    },
  };
});
