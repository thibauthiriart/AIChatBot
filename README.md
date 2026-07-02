# Agent IA Conversation

Base d'agent conversationnel spécialisé pour un site web:

- API FastAPI en Python.
- PostgreSQL avec l'extension `pgvector`.
- Ingestion de pages du site, découpage en chunks et vectorisation.
- Endpoint `/chat` qui répond uniquement à partir des contenus indexés.
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

Si aucune information pertinente n'est trouvée, la réponse est:

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
- Refus immédiat de quelques demandes manifestement généralistes.
- Recherche vectorielle obligatoire avant génération.
- Seuil minimal de pertinence `CHAT_MIN_RELEVANCE`.
- Prompt système qui force la réponse à partir du contexte indexé uniquement.
- Sources retournées avec la réponse pour audit.

Pour un usage production, ajoutez une clé publique par site côté widget, une file de jobs pour l'indexation, et un rate limit distribué type Redis.
