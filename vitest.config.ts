/// <reference types="vitest" />
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// A standalone config rather than a `test` block inside vite.config.ts.
//
// vite.config.ts is built on @lovable.dev/vite-tanstack-config, which pulls in
// TanStack Start, nitro and the SSR entry rewrite. None of that is wanted for a
// unit test run, and reusing it would make the test suite depend on Lovable's
// bundled plugin set. Vitest picks this file up in preference to vite.config.ts,
// so the two stay independent.
//
// The `@/` alias is declared here for the same reason: it normally arrives via
// the Lovable config's bundled tsconfig-paths plugin, which is not loaded here.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // describe/it/expect without importing them in every file.
    globals: true,
    // jsdom throughout, not just for component tests. Splitting environments per
    // directory buys a few milliseconds on the pure-function suites and costs a
    // rule everyone has to remember; at this size it is not worth it.
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // Generated and vendored trees, which contain no tests worth collecting.
    exclude: ["node_modules", "dist", ".output", ".nitro", ".vinxi", "supabase/.temp"],
    // Tailwind's stylesheet is irrelevant to behaviour and slow to transform.
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      // Coverage is reported for the code that carries logic. UI primitives in
      // components/ui are vendored shadcn, and routeTree.gen.ts is generated.
      include: ["src/lib/**/*.ts", "src/components/*.tsx"],
      exclude: ["src/**/*.{test,spec}.{ts,tsx}", "src/test/**"],
    },
  },
});
