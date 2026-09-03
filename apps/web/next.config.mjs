/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // Proxy API/WS server-side so the browser never calls localhost directly.
    // 127.0.0.1 is the native/systemd deployment default (see DEPLOY.md).
    const api = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8085";
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
