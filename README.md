# Agent IA Conversation

Base d'agent conversationnel spécialisé pour une base documentaire client:

- API FastAPI en Python.
- PostgreSQL.
- Ingestion de pages du site et découpage en chunks.
- Endpoint `/chat` qui répond à partir de la base documentaire et des dossiers clients.
- Mode "mémoire client" avec fiches clients, projets, rapports et timeline d'événements.
- Branche de prise de rendez-vous connectable à Google Calendar.
- Widget Vue embeddable.

## Démarrage

```bash
cp .env.example .env
docker compose up -d postgres
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

L'API écoute sur `http://localhost:8000`.

Si votre Docker n'a pas le plugin Compose, lancez PostgreSQL directement:

```bash
docker run --name agentia-postgres \
  -e POSTGRES_DB=agentia \
  -e POSTGRES_USER=agent \
  -e POSTGRES_PASSWORD=agent \
  -p 5432:5432 \
  -v "$PWD/sql/init.sql:/docker-entrypoint-initdb.d/001-init.sql:ro" \
  -d pgvector/pgvector:pg16
```

## Créer un site

```bash
curl -X POST http://localhost:8000/sites \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{"name":"Mon site","base_url":"https://example.com"}'
```

Conservez le `id` retourné.

## Indexer des pages

```bash
curl -X POST http://localhost:8000/knowledge/urls \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "urls": ["https://example.com/page-1", "https://example.com/page-2"]
  }'
```

L'ingestion refuse les URL qui ne sont pas sur le domaine du site.

## Tester le chat

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ou en est le projet support pour Acme ?"}'
```

Si aucune information n'est trouvée dans les dossiers disponibles, la reponse est:

```text
Je n'ai pas assez d'informations dans les dossiers disponibles.
```

## Memoire client

Le backend peut maintenant stocker un contexte CRM/projet par client:

- fiche client generale
- projets et statuts
- rapports / notes / comptes rendus
- historique d'evenements

Creation d'un client:

```bash
curl -X POST http://localhost:8000/clients \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "site_id":"SITE_ID",
    "name":"Acme Industrie",
    "short_name":"Acme",
    "aliases":["Acme SAS"],
    "sector":"Industrie",
    "status":"actif",
    "summary":"Client accompagne sur des cas d usage IA, gouvernance et cadrage projet."
  }'
```

Ajout d'un projet:

```bash
curl -X POST http://localhost:8000/clients/CLIENT_ID/projects \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "name":"Assistant SAV",
    "status":"en cours",
    "summary":"Mise en place d un assistant interne pour le support niveau 1",
    "started_on":"2026-07-01"
  }'
```

Ajout d'un rapport ou compte-rendu:

```bash
curl -X POST http://localhost:8000/clients/CLIENT_ID/artifacts \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "title":"Compte rendu COPIL 8 juillet",
    "kind":"meeting_note",
    "content":"Blocages identifies sur la qualite des donnees produit, arbitrage attendu cote client."
  }'
```

Ajout d'un evenement:

```bash
curl -X POST http://localhost:8000/clients/CLIENT_ID/events \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "title":"COPIL hebdomadaire",
    "event_type":"meeting",
    "details":"Decision de prioriser le lot support et de repousser le lot RH",
    "event_at":"2026-07-08T09:00:00+02:00"
  }'
```

Utilisation dans le chat:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "site_id":"SITE_ID",
    "client_id":"CLIENT_ID",
    "message":"Ou en est Acme sur le projet support et quels blocages ont ete mentionnes ?"
  }'
```

Si `client_id` n'est pas fourni, l'API tente aussi de reconnaitre le client a partir du message et de l'historique en cherchant son nom, son nom court ou ses alias.

## Integration Noota

Le backend peut maintenant recevoir un compte rendu de reunion formate par Noota, le remettre en forme, puis l'enregistrer automatiquement:

- comme artifact `noota_report`
- comme evenement `meeting_report`
- en le rattachant a un client et eventuellement a un projet

Endpoint:

```text
POST /integrations/noota/report
```

Authentification:

- si `NOOTA_INGEST_TOKEN` est configure, envoyez `X-Noota-Token`
- sinon le backend accepte `X-Admin-Token`

Exemple de payload:

```bash
curl -X POST http://localhost:8000/integrations/noota/report \
  -H 'Content-Type: application/json' \
  -H 'X-Noota-Token: change-me' \
  -d '{
    "client_name":"Acme Industrie",
    "project_name":"Assistant SAV",
    "meeting_title":"COPIL hebdomadaire du 10 juillet",
    "meeting_at":"2026-07-10T09:00:00+02:00",
    "external_id":"noota-meeting-7842",
    "source_url":"https://app.noota.io/meetings/7842",
    "summary":"Le client valide la priorite sur le support niveau 1. Le sujet qualite des donnees reste bloquant.",
    "key_points":[
      "Validation du lot support",
      "Besoin de nettoyage des donnees produit"
    ],
    "decisions":[
      "Prioriser le cas d usage SAV",
      "Reporter le chantier RH"
    ],
    "action_items":[
      {
        "description":"Envoyer le plan de remediaton des donnees",
        "owner":"Julie Martin",
        "due_date":"2026-07-15"
      }
    ],
    "participants":[
      {
        "name":"Julie Martin",
        "email":"julie@acme.fr",
        "role":"Directrice operations",
        "company":"Acme Industrie"
      }
    ],
    "transcript":"Transcript complet de la reunion..."
  }'
```

Le backend:

- cree le client s'il n'existe pas encore
- cree le projet s'il n'existe pas encore
- genere un compte rendu structure stocke en base
- ajoute un evenement a la timeline du client

### Sync Google Drive Noota

Si Noota exporte les comptes rendus dans Google Drive au format `.docx`, le backend peut aussi les aspirer directement depuis le dossier racine Drive.

Variables a configurer:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/google-service-account.json
GOOGLE_SERVICE_ACCOUNT_SUBJECT=
NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID=your-google-drive-folder-id
```

Le service account doit avoir acces en lecture au dossier `Noota Reports` et a ses sous-dossiers par date.

Lancer une synchro manuelle:

```bash
curl -X POST http://localhost:8000/integrations/noota/google-drive/sync \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "limit": 20
  }'
```

Comportement actuel du parseur:

- parcours recursif du dossier racine
- import des fichiers `.docx`
- detection de sections Noota comme `Participants`, `Date`, `Ordre du jour`, `Themes abordes`, `Actions`, `Perspectives`
- non reimport du meme fichier grace a son identifiant Google Drive

Convention recommandee pour le nom de fichier / titre de reunion:

```text
Client - Projet - Type de reunion
```

Exemple:

```text
Acme Industrie - Assistant SAV - COPIL hebdomadaire
```

Le parseur utilise cette convention pour deduire `client_name` et `project_name`.

## Widget Vue

```bash
cd widget
npm install
npm run build
```

Documentation d'integration sur un site en production:

```text
docs/integration-widget.md
docs/setup-tokens-google-calendar.md
```

Exemple d'intégration:

```html
<div id="agentia-widget"></div>
<script>
  window.AgentIAConfig = {
    apiUrl: "https://api.votre-domaine.com",
    siteId: "SITE_ID",
    title: "Assistant"
  };
</script>
<script src="/agentia-widget.iife.js"></script>
```

En développement:

```bash
cd widget
npm run dev
```

## Feature Flags

Deux flags `.env` permettent de couper rapidement le widget ou le service de chat:

```env
WIDGET_ENABLED=true
CHAT_SERVICE_ENABLED=true
```

- `WIDGET_ENABLED=false`: le widget ne se monte plus sur le site, meme si le script est charge.
- `CHAT_SERVICE_ENABLED=false`: l'endpoint `/chat` repond toujours `service indisponible`.

Exemple pour desactiver temporairement tout le dispositif:

```env
WIDGET_ENABLED=false
CHAT_SERVICE_ENABLED=false
```

Redemarrez l'API apres modification du `.env`.

## Sécurité applicative

La base inclut plusieurs garde-fous:

- CORS limité par `SITE_ALLOWED_ORIGINS`.
- Token admin `X-Admin-Token` sur `/sites` et `/ingest`.
- Rate limit simple par IP sur `/chat`.
- Routage LLM avant reponse pour bloquer les attaques de prompt et les demandes hors perimetre.
- Prompt système qui force la réponse à partir du contexte indexé uniquement.
- Sources retournées avec la réponse pour audit.

Modele de routage par defaut: `OPENAI_ROUTER_MODEL=gpt-4.1-mini`.

Pour un usage production, ajoutez une clé publique par site côté widget, une file de jobs pour l'indexation, et un rate limit distribué type Redis.

## Reservation et Google Calendar

Le meme endpoint `/chat` peut maintenant traiter une intention de reservation. Le flux reste cote serveur:

- detection de l'intention `appointment`
- collecte du nom, de l'email et d'une date explicite
- lecture de vrais creneaux dans Google Calendar
- creation de l'evenement uniquement apres confirmation explicite

Variables a configurer:

```text
BOOKING_PROVIDER=google_calendar
GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/google-service-account.json
GOOGLE_SERVICE_ACCOUNT_SUBJECT=
```

Le compte de service doit avoir acces en lecture/ecriture au calendrier cible. Si votre Google Workspace impose une delegation domaine, utilisez `GOOGLE_SERVICE_ACCOUNT_SUBJECT`.
