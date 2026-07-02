<script setup lang="ts">
import { computed, ref } from 'vue'

type Source = {
  url: string
  title: string
  score: number
}

type ChatMessage = {
  role: 'visitor' | 'agent'
  content: string
}

const props = withDefaults(
  defineProps<{
    apiUrl: string
    siteId: string
    title?: string
  }>(),
  {
    title: 'Assistant'
  }
)

const isOpen = ref(false)
const isLoading = ref(false)
const draft = ref('')
const messages = ref<ChatMessage[]>([
  { role: 'agent', content: 'Bonjour, posez-moi une question sur le site.' }
])

const canSend = computed(() => draft.value.trim().length > 0 && !isLoading.value)

async function sendMessage() {
  const message = draft.value.trim()
  if (!message || isLoading.value) return

  const history = messages.value
    .slice(-6)
    .filter((item) => !(item.role === 'agent' && item.content === 'Bonjour, posez-moi une question sur le site.'))
    .map((item) => ({ role: item.role, content: item.content }))
  messages.value.push({ role: 'visitor', content: message })
  draft.value = ''
  isLoading.value = true

  try {
    const response = await fetch(`${props.apiUrl.replace(/\/$/, '')}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site_id: props.siteId, message, history })
    })

    if (!response.ok) {
      throw new Error('Chat request failed')
    }

    const data = await response.json()
    messages.value.push({
      role: 'agent',
      content: data.answer
    })
  } catch {
    messages.value.push({
      role: 'agent',
      content: "Le service est temporairement indisponible."
    })
  } finally {
    isLoading.value = false
  }
}

function onTextareaKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void sendMessage()
}
</script>

<template>
  <section class="agentia">
    <button class="agentia__launcher" type="button" @click="isOpen = !isOpen" aria-label="Ouvrir le chat">
      <span v-if="!isOpen">?</span>
      <span v-else>x</span>
    </button>

    <div v-if="isOpen" class="agentia__panel">
      <header class="agentia__header">
        <strong>{{ title }}</strong>
      </header>

      <div class="agentia__messages" aria-live="polite">
        <article
          v-for="(message, index) in messages"
          :key="index"
          class="agentia__message"
          :class="`agentia__message--${message.role}`"
        >
          <p>{{ message.content }}</p>
        </article>
        <p v-if="isLoading" class="agentia__typing">...</p>
      </div>

      <form class="agentia__form" @submit.prevent="sendMessage">
        <textarea
          v-model="draft"
          rows="2"
          maxlength="1200"
          placeholder="Votre question"
          @keydown="onTextareaKeydown"
        />
        <button type="submit" :disabled="!canSend">Envoyer</button>
      </form>
    </div>
  </section>
</template>
