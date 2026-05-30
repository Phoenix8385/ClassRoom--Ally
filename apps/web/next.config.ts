import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root so Turbopack does not walk up and mis-detect a
  // stray lockfile (e.g. one in the home directory) as the project root.
  turbopack: {
    root: path.resolve(__dirname, "..", ".."),
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
