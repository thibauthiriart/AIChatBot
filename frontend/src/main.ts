import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

const target = document.querySelector('#app')

if (!target) {
  throw new Error('AgentIA app root not found: #app')
}

createApp(App).mount(target)
