<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()
const messagesContainer = ref<HTMLElement | null>(null)

function onTextareaKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void state.sendMessage()
}

watch(
  () => state.messages.value.length,
  async () => {
    await nextTick()
    messagesContainer.value?.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth'
    })
  },
  { immediate: true }
)

onMounted(async () => {
  await nextTick()
  messagesContainer.value?.scrollTo({ top: messagesContainer.value.scrollHeight })
})
</script>

<template>
  <section class="chat-panel">
    <header class="chat-panel__header">
      <div>
        <p class="section-eyebrow">Session active</p>
        <h1>{{ state.activeConversationTitle.value }}</h1>
      </div>
      <span class="chat-panel__status">En ligne</span>
    </header>

    <div ref="messagesContainer" class="chat-panel__messages" aria-live="polite">
      <article
        v-for="(message, index) in state.messages.value"
        :key="index"
        class="chat-message"
        :class="`chat-message--${message.role}`"
      >
        <div v-if="message.role === 'agent'" class="chat-message__avatar">IA</div>

        <div class="chat-message__content">
          <div class="chat-message__meta">
            <span>{{ message.role === 'agent' ? state.config.title : 'Vous' }}</span>
            <time>{{ message.createdAt }}</time>
          </div>

          <div class="chat-message__bubble">
            <p>{{ message.content }}</p>
          </div>

          <div v-if="message.role === 'agent' && message.sources?.length" class="chat-message__tools">
            <button class="chat-message__source-button" type="button" @click="state.openSourcesForMessage(message)">
              Voir les documents relies
            </button>
            <span class="chat-message__source-count">{{ message.sources.length }} document(s)</span>
          </div>
        </div>
      </article>

      <article v-if="state.isLoading.value" class="chat-message chat-message--agent">
        <div class="chat-message__avatar">IA</div>
        <div class="chat-message__content">
          <div class="chat-message__meta">
            <span>{{ state.config.title }}</span>
            <time>...</time>
          </div>
          <div class="chat-message__bubble chat-message__bubble--typing">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </article>
    </div>

    <form class="chat-panel__composer" @submit.prevent="state.sendMessage()">
      <label class="sr-only" for="agentia-message">Message</label>
      <div class="chat-panel__composer-box">
        <textarea
          id="agentia-message"
          v-model="state.draft.value"
          rows="3"
          maxlength="1200"
          placeholder="Posez une question precise sur le client, les actions a venir ou les documents."
          @keydown="onTextareaKeydown"
        />
        <div class="chat-panel__composer-actions">
          <span>{{ state.draft.value.length }}/1200</span>
          <button type="submit" :disabled="!state.canSend.value">Envoyer</button>
        </div>
      </div>
    </form>
  </section>
</template>
