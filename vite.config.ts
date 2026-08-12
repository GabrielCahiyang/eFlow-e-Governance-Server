import { defineConfig, loadEnv } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  // Load .env vars so they are available via process.env in this config
  const env = loadEnv(mode, __dirname, '');
  Object.assign(process.env, env);

  return {
    plugins: [
      figmaAssetResolver(),
      // The React and Tailwind plugins are both required for Make, even if
      // Tailwind is not being actively used – do not remove them
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        // Alias @ to the src directory
        '@': path.resolve(__dirname, './src'),
      },
    },

    // Proxy API requests to the local Python LLM backend
    server: {
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8321',
          changeOrigin: true,
          rewrite: (p) => `/controlpanelEflow${p}`,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              const key = process.env.VITE_BACKEND_API_KEY ?? '';
              const existingAuth = proxyReq.getHeader('authorization');
              if (!existingAuth && key) {
                proxyReq.setHeader('Authorization', `Bearer ${key}`);
              }
            });
          },
        },
      },
    },

    // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
    assetsInclude: ['**/*.svg', '**/*.csv'],
  };
})
