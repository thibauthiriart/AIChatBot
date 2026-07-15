<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAgentiaState } from './composables/useAgentiaState'
import ConversationHistory from './components/ConversationHistory.vue'
import DashboardView from './components/DashboardView.vue'
import DriveMonitoringView from './components/DriveMonitoringView.vue'
import NotificationCenter from './components/NotificationCenter.vue'
import PendingReportModal from './components/PendingReportModal.vue'

const state = useAgentiaState()

type PageId = 'dashboard' | 'drive'

function pageFromHash(hash: string): PageId {
  return hash === '#/drive' ? 'drive' : 'dashboard'
}

const currentPage = ref<PageId>(pageFromHash(window.location.hash))

function syncPageFromHash() {
  currentPage.value = pageFromHash(window.location.hash)
}

function navigate(page: PageId) {
  window.location.hash = page === 'drive' ? '/drive' : '/dashboard'
}

const currentView = computed(() => (currentPage.value === 'drive' ? DriveMonitoringView : DashboardView))

onMounted(() => {
  if (!window.location.hash) {
    window.location.hash = '/dashboard'
  }
  syncPageFromHash()
  window.addEventListener('hashchange', syncPageFromHash)
  void state.startPolling()
})

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncPageFromHash)
  state.stopPolling()
})
</script>

<template>
  <section class="app-frame">
    <NotificationCenter />
    <PendingReportModal />

    <header class="topbar">
      <div>
        <p class="section-eyebrow">AgentIA</p>
        <h1>{{ state.config.title }}</h1>
      </div>

      <nav class="topbar__nav" aria-label="Navigation principale">
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'dashboard' }"
          @click="navigate('dashboard')"
        >
          Dashboard
        </button>
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'drive' }"
          @click="navigate('drive')"
        >
          Surveillance Drive
        </button>
      </nav>
    </header>

    <div class="workspace">
      <aside class="workspace__sidebar">
        <ConversationHistory />
      </aside>

      <main class="workspace__main">
        <component :is="currentView" />
      </main>
    </div>
  </section>
</template>
