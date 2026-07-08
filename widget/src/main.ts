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

async function isWidgetEnabled(apiUrl: string): Promise<boolean> {
  try {
    const response = await fetch(`${apiUrl.replace(/\/$/, '')}/widget-config`)
    if (!response.ok) {
      return true
    }

    const data = await response.json()
    return data.widget_enabled !== false
  } catch {
    return true
  }
}

window.AgentIAWidget = { mount }

if (window.AgentIAConfig) {
  void isWidgetEnabled(window.AgentIAConfig.apiUrl).then((enabled) => {
    if (!enabled) {
      return
    }
    mount('#agentia-widget', window.AgentIAConfig!)
  })
}
