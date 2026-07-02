import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    lib: {
      entry: 'src/main.ts',
      name: 'AgentIAWidget',
      fileName: 'agentia-widget',
      formats: ['iife']
    }
  }
})
