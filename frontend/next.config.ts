import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Smaller production image -- only the files actually needed at runtime
  // get copied into the final Docker stage (see frontend/Dockerfile).
  output: "standalone",
};

export default nextConfig;
