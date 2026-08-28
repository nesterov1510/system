/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // Proxy API/WS to the backend so the browser never calls localhost directly.
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8085";
    return [
      {
        source: "/api/:path*",
        destination: `${api}/api/:path*`,
      },
      {
        source: "/docs/:path*",
        destination: `${api}/docs/:path*`,
      },
      {
        source: "/media/:path*",
        destination: `${api}/media/:path*`,
      },
      {
        source: "/ws",
        destination: `${api}/ws`,
      },
    ];
  },
};

export default nextConfig;
