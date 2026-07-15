<script setup lang="ts">
import { formatAppointmentDate, formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()
</script>

<template>
  <div class="toast-stack" aria-live="polite" aria-atomic="false">
    <article v-for="report in state.pendingNootaToasts.value" :key="report.external_id" class="toast toast--action">
      <div class="toast__header">
        <p>Nouveau compte rendu Drive</p>
        <button type="button" aria-label="Fermer la notification" @click="state.dismissPendingNootaToast(report.external_id)">
          ×
        </button>
      </div>
      <strong>{{ report.meeting_title }}</strong>
      <span>{{ report.client_name }}<template v-if="report.project_name"> · {{ report.project_name }}</template></span>
      <span v-if="report.meeting_at">{{ formatConversationDate(report.meeting_at) }}</span>
      <span>{{ report.file_name }}</span>
      <div class="toast__actions">
        <button type="button" class="toast__primary" @click="state.openPendingNootaPreview(report)">
          Lire, valider et envoyer
        </button>
      </div>
    </article>

    <article v-for="toast in state.appointmentToasts.value" :key="toast.id" class="toast">
      <div class="toast__header">
        <p>Nouveau rendez-vous</p>
        <button type="button" aria-label="Fermer la notification" @click="state.dismissToast(toast.id)">Fermer</button>
      </div>
      <strong>{{ toast.client_name || 'Client sans nom' }}</strong>
      <span>{{ formatAppointmentDate(toast.scheduled_for, toast.timezone) }} · {{ toast.timezone }}</span>
      <span v-if="toast.client_email">{{ toast.client_email }}</span>
      <a v-if="toast.html_link" :href="toast.html_link" target="_blank" rel="noreferrer">Ouvrir le rendez-vous</a>
    </article>
  </div>
</template>
