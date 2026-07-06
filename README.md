# Agent IA Conversation

Base d'agent conversationnel spécialisé pour un site web:

- API FastAPI en Python.
- PostgreSQL.
- Ingestion de pages du site et découpage en chunks.
- Endpoint `/chat` qui répond uniquement à partir des contenus indexés.
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
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: change-me' \
  -d '{
    "site_id": "SITE_ID",
    "urls": ["https://example.com/page-1", "https://example.com/page-2"]
  }'
```

L'ingestion refuse les URL qui ne sont pas sur le domaine du site.

## Tester le chat

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"site_id":"SITE_ID","message":"Que propose ce site ?"}'
```

Si aucune information n'est trouvée dans les contenus indexes, la reponse est:

```text
Le site ne traite pas de ce sujet.
```

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
