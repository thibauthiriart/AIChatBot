<script setup lang="ts">
import { computed } from 'vue'
import { formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()

const driveMetrics = computed(() => [
  {
    label: 'Fichiers scannes',
    value: String(state.driveStatus.value?.scanned_files ?? 0)
  },
  {
    label: 'Fichiers en attente',
    value: String(state.driveStatus.value?.pending_files ?? state.pendingNootaToasts.value.length)
  },
  {
    label: 'Rapports importes',
    value: String(state.driveStatus.value?.imported_reports ?? 0)
  }
])
</script>

<template>
  <section class="page-view">
    <div class="page-view__hero page-view__hero--compact">
      <div>
        <p class="section-eyebrow">Drive</p>
        <h2>Surveillance et validation des comptes rendus</h2>
        <p class="page-view__intro">
          Cette page concentre l’etat du dossier surveille, les rapports en attente et les derniers fichiers detectes par le backend.
        </p>
      </div>
      <button type="button" class="primary-button" @click="state.refreshDriveMonitoring()">Rafraichir</button>
    </div>

    <div class="metric-grid metric-grid--compact">
      <article v-for="metric in driveMetrics" :key="metric.label" class="metric-card">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </article>
    </div>

    <div class="drive-grid">
      <section class="info-card">
        <div class="info-card__header">
          <div>
            <p class="section-eyebrow">Etat</p>
            <h3>Connecteur Drive</h3>
          </div>
        </div>

        <div class="info-card__stack">
          <article class="list-card">
            <p class="list-card__title">Derniere synchronisation</p>
            <p class="list-card__meta" v-if="state.driveStatusLoading.value">Chargement...</p>
            <p class="list-card__meta" v-else-if="state.driveStatusError.value">{{ state.driveStatusError.value }}</p>
            <template v-else-if="state.driveStatus.value">
              <p class="list-card__meta">Dernier check: {{ formatConversationDate(state.driveStatus.value.checked_at) }}</p>
              <p class="list-card__meta">{{ state.driveStatus.value.scanned_files }} fichier(s) visibles</p>
              <p class="list-card__meta">{{ state.driveStatus.value.pending_files }} element(s) a traiter</p>
              <p class="list-card__meta">{{ state.driveStatus.value.imported_reports }} import(s) realises</p>
            </template>
            <p v-else class="list-card__meta">Aucune information Drive disponible.</p>
          </article>
        </div>
      </section>

      <section class="info-card">
        <div class="info-card__header">
          <div>
            <p class="section-eyebrow">Validation</p>
            <h3>Rapports en attente</h3>
          </div>
        </div>

        <div v-if="state.pendingNootaToasts.value.length" class="info-card__stack">
          <article v-for="report in state.pendingNootaToasts.value" :key="report.external_id" class="list-card list-card--action">
            <p class="list-card__title">{{ report.meeting_title }}</p>
            <p class="list-card__meta">{{ report.client_name }}<template v-if="report.project_name"> · {{ report.project_name }}</template></p>
            <p class="list-card__meta">{{ report.file_name }}</p>
            <button type="button" class="secondary-button" @click="state.openPendingNootaPreview(report)">
              Lire, valider et envoyer
            </button>
          </article>
        </div>
        <p v-else class="empty-state">Aucun rapport Drive en attente de validation.</p>
      </section>

      <section class="info-card">
        <div class="info-card__header">
          <div>
            <p class="section-eyebrow">Fichiers</p>
            <h3>Derniers elements detectes</h3>
          </div>
        </div>

        <div v-if="state.driveStatus.value?.latest_files?.length" class="info-card__stack">
          <article v-for="file in state.driveStatus.value.latest_files" :key="file.external_id" class="list-card">
            <p class="list-card__title">{{ file.file_name }}</p>
            <p class="list-card__meta">Modifie le {{ formatConversationDate(file.modified_time) }}</p>
          </article>
        </div>
        <p v-else-if="!state.driveStatusLoading.value" class="empty-state">
          Le backend ne renvoie pas encore de liste de fichiers visibles.
        </p>
      </section>
    </div>
  </section>
</template>
