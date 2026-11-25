import type { NextConfig } from "next";

/**
 * Cache Components and partial prefetching are off on purpose. Every page here is a
 * client-rendered workspace over the local JobOrbit API (TanStack Query), so prerendering
 * buys nothing, and its rules would reject ordinary client code such as "time since posted".
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
