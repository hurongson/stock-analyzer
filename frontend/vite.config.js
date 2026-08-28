import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'robots.txt'],
      manifest: {
        name: '股票分析助手',
        short_name: '股票助手',
        description: 'AI驱动的股票分析与选股系统，五维评分、买卖信号、尾盘选股',
        theme_color: '#1a1a2e',
        background_color: '#1a1a2e',
        display: 'standalone',
        orientation: 'portrait',
        scope: './',
        start_url: './',
        lang: 'zh-CN',
        categories: ['finance', 'business', 'productivity'],
        icons: [
          {
            src: 'icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: 'icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: 'icons/icon-1024.png',
            sizes: '1024x1024',
            type: 'image/png',
            purpose: 'any maskable'
          }
        ],
        shortcuts: [
          {
            name: '自选股分析',
            short_name: '自选股',
            description: '查看自选股买卖信号',
            url: './?page=dashboard',
            icons: [{ src: 'icons/icon-192.png', sizes: '192x192' }]
          },
          {
            name: '选股结果',
            short_name: '选股',
            description: '查看五大策略选股结果',
            url: './?page=screener',
            icons: [{ src: 'icons/icon-192.png', sizes: '192x192' }]
          }
        ]
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/.*\.json$/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'json-data',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24
              },
              cacheableResponse: {
                statuses: [0, 200]
              }
            }
          },
          {
            urlPattern: /^https:\/\/.*\.(?:png|jpg|jpeg|svg|gif|webp)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'images',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 * 24 * 7
              }
            }
          }
        ]
      },
      devOptions: {
        enabled: false
      }
    })
  ],
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/data': {
        target: 'http://localhost:5173',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
