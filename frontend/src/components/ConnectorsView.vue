<script setup lang="ts">
const connectors = [
  {
    name: 'Google Calendar',
    badge: 'Actif',
    accentClass: 'connector-card--calendar',
    summary: 'Planification, consultation des disponibilites et creation de rendez-vous.',
    capabilities: ['Lecture des agendas', 'Suggestion de creneaux', 'Creation d evenements'],
    status: 'Connecteur disponible dans l assistant'
  },
  {
    name: 'Google Drive',
    badge: 'Actif',
    accentClass: 'connector-card--drive',
    summary: 'Surveillance du dossier source, detection des nouveaux fichiers et suivi des imports.',
    capabilities: ['Scan du dossier surveille', 'Liste des derniers fichiers', 'Suivi des rapports en attente'],
    status: 'Connecteur disponible dans l interface'
  },
  {
    name: 'Noota',
    badge: 'Actif',
    accentClass: 'connector-card--noota',
    summary: 'Traitement des comptes rendus, reformulation et preparation des envois clients.',
    capabilities: ['Validation de comptes rendus', 'Reecriture avant envoi', 'Preparation des suggestions de rendez-vous'],
    status: 'Connecteur disponible dans le flux Drive'
  }
]
</script>

<template>
  <section class="page-view">
    <div class="page-view__hero">
      <div>
        <p class="section-eyebrow">Connecteurs</p>
        <h2>Connecteurs actuellement disponibles</h2>
        <p class="page-view__intro">
          Cette page recense les integrations visibles dans l application a ce stade: Google Calendar, Google Drive et Noota.
        </p>
      </div>
    </div>

    <div class="connectors-grid">
      <article v-for="connector in connectors" :key="connector.name" class="connector-card" :class="connector.accentClass">
        <div class="connector-card__header">
          <div>
            <p class="connector-card__eyebrow">{{ connector.badge }}</p>
            <h3>{{ connector.name }}</h3>
          </div>
          <span class="connector-card__status">{{ connector.status }}</span>
        </div>

        <p class="connector-card__summary">{{ connector.summary }}</p>

        <ul class="connector-card__list">
          <li v-for="capability in connector.capabilities" :key="capability">
            {{ capability }}
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>
