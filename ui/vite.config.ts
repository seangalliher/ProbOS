import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:18900',
      '/ws': {
        target: 'ws://127.0.0.1:18900',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // BF-301: transformers.js + bundled onnxruntime-web for browser STT.
          // Loaded only when the PTT handler arms (lazy `import('../audio/transformersStt')`).
          if (
            id.includes('node_modules/@huggingface/transformers') ||
            id.includes('node_modules/onnxruntime-web') ||
            id.includes('/ui/src/audio/transformersStt') ||
            id.includes('/ui/src/audio/transformersWorker')
          ) {
            return 'stt-vendor';
          }
          // Vendor: three.js + @pixiv/three-vrm. Heavy, only avatar/canvas
          // surfaces need them; defer until the App chunk is loaded.
          if (
            id.includes('node_modules/three/') ||
            id.includes('node_modules/@pixiv/three-vrm')
          ) {
            return 'avatar-vendor';
          }
          // App-side code that depends on three.js: canvas/* and avatar
          // components. Grouping these prevents Rollup from re-fanning
          // three-dependent modules back into the main chunk.
          if (
            id.includes('/ui/src/canvas/') ||
            id.includes('/ui/src/components/profile/CrewVRM') ||
            id.includes('/ui/src/components/profile/ParametricAvatar') ||
            id.includes('/ui/src/components/profile/MemoryGraph3D') ||
            id.includes('/ui/src/components/profile/CrewAvatarPopout') ||
            id.includes('/ui/src/components/spatial/ShipLayoutView') ||
            id.includes('/ui/src/components/CognitiveCanvas')
          ) {
            return 'avatar-app';
          }
        },
      },
    },
  },
})
