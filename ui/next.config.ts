import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  pageExtensions: ['tsx', 'ts', 'jsx', 'js'],
  reactStrictMode: true,
  
  // Transpile Jupiter DS package to handle CSS imports
  transpilePackages: ['@rungalileo/jupiter-ds'],
  
  // Configure webpack to ignore CSS imports from Jupiter DS
  // (we import the CSS manually in _app.tsx)
  webpack: (config) => {
    const webpack = require('webpack');
    
    // Replace CSS imports from Jupiter DS with empty module
    config.plugins.push(
      new webpack.NormalModuleReplacementPlugin(
        /^@mantine\/dates\/styles\.css$/,
        (resource: any) => {
          // Only replace if imported from Jupiter DS
          if (resource.context && resource.context.includes('@rungalileo/jupiter-ds')) {
            resource.request = require.resolve('./empty-css-module.js');
          }
        }
      )
    );
    
    return config;
  },
  
  // Optimize for CI/test builds
  ...(process.env.CI && {
    // Disable source maps in CI (faster builds, not needed for tests)
    productionBrowserSourceMaps: false,
    
    // Optimize images (if using next/image) - skip optimization in CI
    images: {
      unoptimized: true,
    },
    
    // Use SWC minification (faster than Terser, default in Next.js 15)
    swcMinify: true,
    
    // Compiler optimizations
    compiler: {
      removeConsole: process.env.CI ? {
        exclude: ['error', 'warn'], // Keep errors/warnings for debugging
      } : false,
    },
  }),
};

export default nextConfig;
