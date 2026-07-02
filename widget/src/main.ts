import { createApp } from 'vue'
import ChatWidget from './ChatWidget.vue'
import './style.css'

declare global {
  interface Window {
    AgentIAWidget?: {
      mount: (selector: string, options: WidgetOptions) => void
    }
    AgentIAConfig?: WidgetOptions
  }
}

export type WidgetOptions = {
  apiUrl: string
  siteId: string
  title?: string
}

function mount(selector: string, options: WidgetOptions) {
  const target = document.querySelector(selector)
  if (!target) {
    throw new Error(`AgentIA widget target not found: ${selector}`)
  }
  createApp(ChatWidget, options).mount(target)
}

window.AgentIAWidget = { mount }

if (window.AgentIAConfig) {
  mount('#agentia-widget', window.AgentIAConfig)
}
