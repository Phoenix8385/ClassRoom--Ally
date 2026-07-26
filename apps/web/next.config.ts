import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root so Turbopack does not walk up and mis-detect a
  // stray lockfile (e.g. one in the home directory) as the project root.
  turbopack: {
    root: path.resolve(__dirname, "..", ".."),
  },
  // Carried over from the former next.config.mjs (v0.dev export).
  // NOTE: ignoreBuildErrors hides real TS errors from `next build` — worth
  // removing once the codebase typechecks cleanly under the project config.
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async headers() {
    return [
      {
        // The AudioWorklet module is served from /public as a static asset.
        // Pin its MIME type and allow long-lived caching.
        source: "/audio-worklet-processor.js",
        headers: [
          { key: "Content-Type", value: "text/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
    ];
  },
};

export default nextConfig;
