<script setup lang="ts">
import { ref } from 'vue'
import { formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()

const editingConversationId = ref('')
const editingTitle = ref('')

function startTitleEdit(id: string, title: string) {
  editingConversationId.value = id
  editingTitle.value = title
}

function saveTitleEdit(id: string) {
  state.renameConversation(id, editingTitle.value)
  editingConversationId.value = ''
  editingTitle.value = ''
}

function cancelTitleEdit() {
  editingConversationId.value = ''
  editingTitle.value = ''
}
</script>

<template>
  <section class="history-panel">
    <div class="history-panel__header">
      <div>
        <p class="section-eyebrow">Historique</p>
        <h2>Conversations</h2>
      </div>
      <button type="button" class="history-panel__new" @click="state.startNewConversation()">Nouvelle conversation</button>
    </div>

    <div class="history-panel__list">
      <article
        v-for="conversation in state.conversations.value"
        :key="conversation.id"
        class="history-item"
        :class="{ 'history-item--active': conversation.id === state.activeConversationId.value }"
      >
        <div v-if="editingConversationId === conversation.id" class="history-item__editor">
          <input
            v-model="editingTitle"
            class="history-item__input"
            type="text"
            maxlength="80"
            @keydown.enter.prevent="saveTitleEdit(conversation.id)"
            @keydown.esc.prevent="cancelTitleEdit"
          />
          <div class="history-item__actions">
            <button type="button" class="history-item__link" @click="saveTitleEdit(conversation.id)">OK</button>
            <button type="button" class="history-item__danger" @click="cancelTitleEdit()">Annuler</button>
          </div>
        </div>

        <template v-else>
          <button type="button" class="history-item__open" @click="state.openConversation(conversation.id)">
            <strong>{{ conversation.title }}</strong>
            <span>{{ formatConversationDate(conversation.updatedAt) }}</span>
          </button>
          <div class="history-item__actions">
            <button
              type="button"
              class="history-item__link"
              aria-label="Renommer la conversation"
              @click="startTitleEdit(conversation.id, conversation.title)"
            >
              Renommer
            </button>
            <button
              type="button"
              class="history-item__danger"
              aria-label="Supprimer la conversation"
              @click="state.deleteConversation(conversation.id)"
            >
              Supprimer
            </button>
          </div>
        </template>
      </article>
    </div>
  </section>
</template>
