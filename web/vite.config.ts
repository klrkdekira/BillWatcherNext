import { copyFileSync, existsSync, readFileSync, statSync } from "node:fs";
import { createReadStream } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * The pipeline's own `.env` is the single authority for where the tree lives (`SITE_ROOT`) and
 * what it is served as (`SITE_PREFIX`, whose path part — `cheeleong.dev/data-parlimen` — is the
 * base every asset URL and fetch must carry on a path-hosted Pages site). Read here rather than
 * configured a second time in the frontend, where the two copies would eventually disagree.
 */
function pipelineEnv(name: string): string | undefined {
  for (const file of [".env", ".env.development"]) {
    const path = resolve(import.meta.dirname, "..", file);
    if (!existsSync(path)) continue;
    const match = readFileSync(path, "utf-8").match(new RegExp(`^${name}=(.*)$`, "m"));
    if (match) return match[1].trim();
  }
  return undefined;
}

const SITE_ROOT = resolve(import.meta.dirname, "..", pipelineEnv("SITE_ROOT") || "docs");

function basePath(): string {
  const prefix = (pipelineEnv("SITE_PREFIX") || "").replace(/^https?:\/\//, "").replace(/\/+$/, "");
  const path = prefix.split("/").slice(1).join("/");
  return path ? `/${path}/` : "/";
}

const CONTENT_TYPES: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".jsonld": "application/ld+json; charset=utf-8",
  ".nq": "application/n-quads; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
};

/**
 * Serve the published dataset in `pnpm dev`.
 *
 * The dataset is written by the Python pipeline into the same directory Vite builds into, so in
 * production the browser fetches `/index.json` and `/akn/...` from the same origin as the app.
 * Without this, development is the one place where those paths 404 — and the app would be built
 * against a fixture that can silently drift from the bytes it ships beside.
 */
function serveThePublishedDataset(): Plugin {
  return {
    name: "billwatcher:dataset",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        let path = decodeURIComponent((request.url ?? "/").split("?")[0] ?? "/");
        // In dev the app is served under the same base as in production, so dataset fetches
        // arrive base-prefixed too; the published tree itself is laid out from its own root.
        const base = basePath();
        if (base !== "/" && path.startsWith(base)) path = `/${path.slice(base.length)}`;
        if (!/^\/(index\.json|checksums\.sha256|akn\/|definitions\/)/.test(path)) return next();

        // `normalize` before joining: a request may not climb out of the published tree.
        const file = join(SITE_ROOT, normalize(path));
        if (!file.startsWith(SITE_ROOT) || !existsSync(file) || !statSync(file).isFile()) {
          return next();
        }
        response.setHeader(
          "Content-Type",
          CONTENT_TYPES[extname(file)] ?? "application/octet-stream",
        );
        createReadStream(file).pipe(response);
      });
    },
  };
}

/**
 * GitHub Pages serves `404.html` for any path with no file behind it, which is exactly what an
 * FRBR work URI is: `/akn/my/bill/dr/2024/11` is a directory holding `msa@.jsonld`, not a page.
 * Shipping the app as `404.html` too is what makes those identifiers resolve in a browser instead
 * of dead-ending — and it costs one copy, because a real file still wins over the fallback.
 */
function fallbackForFrbrPaths(): Plugin {
  return {
    name: "billwatcher:404-fallback",
    apply: "build",
    closeBundle() {
      const index = resolve(SITE_ROOT, "index.html");
      if (existsSync(index)) copyFileSync(index, resolve(SITE_ROOT, "404.html"));
    },
  };
}

export default defineConfig({
  // On a path-hosted Pages site every built asset URL starts with the repository's path; at a
  // domain root this is "/" and nothing changes.
  base: basePath(),
  plugins: [react(), serveThePublishedDataset(), fallbackForFrbrPaths()],
  build: {
    outDir: SITE_ROOT,
    // `docs/` has two writers. `billwatcher publish` owns the dataset — `akn/`, `definitions/`,
    // `index.json`, `checksums.sha256`, `CNAME` — and emptying the directory here would delete a
    // published corpus that took a live crawl to produce. Vite reconciles only its own output.
    emptyOutDir: false,
    assetsDir: "assets",
    // Sourcemaps are not published: `docs/` is committed, and a 2 MB map rewritten on every
    // build would churn the repository harder than the dataset it sits beside.
    sourcemap: false,
  },
});
