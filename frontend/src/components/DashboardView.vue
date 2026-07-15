<script setup lang="ts">
import { computed } from 'vue'
import { formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'
import ChatPanel from './ChatPanel.vue'

const state = useAgentiaState()

const metrics = computed(() => [
  {
    label: 'Conversations',
    value: String(state.conversations.value.length),
    detail: 'Historique local disponible'
  },
  {
    label: 'En attente Drive',
    value: String(state.pendingNootaToasts.value.length),
    detail: 'Comptes rendus a valider'
  },
  {
    label: 'Dernier check Drive',
    value: state.driveStatus.value ? formatConversationDate(state.driveStatus.value.checked_at) : 'Indisponible',
    detail: state.driveStatusError.value || 'Surveillance backend active'
  }
])
</script>

<template>
  <section class="page-view">
    <div class="page-view__hero">
      <div>
        <p class="section-eyebrow">Dashboard</p>
        <h2>Pilotage conversationnel et suivi operationnel</h2>
        <p class="page-view__intro">
          Le chat reste central, avec l’historique a gauche, les documents relies a droite et l’etat Drive accessible sans quitter l’application.
        </p>
      </div>
      <div class="metric-grid">
        <article v-for="metric in metrics" :key="metric.label" class="metric-card">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <p>{{ metric.detail }}</p>
        </article>
      </div>
    </div>

    <div class="dashboard-grid">
      <ChatPanel />

      <aside class="insights-panel">
        <section class="info-card">
          <div class="info-card__header">
            <div>
              <p class="section-eyebrow">Documents</p>
              <h3>Sources reliees</h3>
            </div>
          </div>

          <div v-if="state.hasSelectedSources.value" class="info-card__stack">
            <div v-if="state.selectedClient.value" class="client-chip-list">
              <strong>{{ state.selectedClient.value.name }}</strong>
              <span v-if="state.selectedClient.value.status">{{ state.selectedClient.value.status }}</span>
              <span v-if="state.selectedClient.value.sector">{{ state.selectedClient.value.sector }}</span>
            </div>

            <article v-for="source in state.selectedSources.value" :key="source.url" class="list-card">
              <p class="list-card__title">{{ source.title || 'Document sans titre' }}</p>
              <p class="list-card__meta">{{ source.url }}</p>
              <p class="list-card__meta">Score {{ source.score.toFixed(2) }}</p>
            </article>
          </div>

          <p v-else class="empty-state">
            Selectionnez une reponse avec sources pour afficher ici les documents relies et le contexte client.
          </p>
        </section>
      </aside>
    </div>
  </section>
</template>
