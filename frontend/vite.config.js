import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import istanbul from "vite-plugin-istanbul";

// COVERAGE=1 instruments the bundle so the Playwright suite can collect real
// line coverage from the running app. It is off for normal dev and for the
// production build, which must never ship instrumented code.
const withCoverage = process.env.COVERAGE === "1";

export default defineConfig({
  plugins: [
    react(),
    withCoverage &&
      istanbul({
        include: "src/*",
        exclude: ["node_modules", "tests/"],
        extension: [".js", ".jsx"],
        requireEnv: false,
        // Without this the plugin only instruments the dev server. The e2e
        // suite runs against the production bundle, so the build has to be
        // instrumented too.
        forceBuildInstrument: true,
      }),
  ].filter(Boolean),
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // `npm run dev` serves the UI; the API stays on the Python server.
      // MILSURP_API_PORT is exported by `make dev-frontend` so this follows
      // the dynamically chosen backend port.
      "/api": {
        target: `http://127.0.0.1:${process.env.MILSURP_API_PORT || 8730}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: withCoverage,
    rollupOptions: {
      output: {
        // Keep React in its own chunk so an app-code change does not force
        // every visitor to re-download the framework.
        //
        // Written as a function rather than the `{ vendor: [...] }` object
        // form: Vite 8 bundles with Rolldown, which only accepts a function.
        manualChunks(id) {
          return /node_modules[/\\](react|react-dom|react-router|react-router-dom|scheduler)[/\\]/.test(
            id,
          )
            ? "vendor"
            : undefined;
        },
      },
    },
  },
});
