import type { NextConfig } from "next";
import path from "node:path";

const monorepoRoot = path.join(__dirname, "..");

const nextConfig: NextConfig = {
  outputFileTracingRoot: monorepoRoot,
  serverExternalPackages: ["@databricks/sql", "lz4"],
  turbopack: {
    root: monorepoRoot,
  },
};

export default nextConfig;
