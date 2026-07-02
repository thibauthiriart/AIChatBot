# Integration du widget sur un site en production

Cette page explique comment ajouter le widget de chat sur un site deja en ligne.

## Principe

Le site public charge seulement le widget JavaScript.

La logique sensible reste cote API:

- cle OpenAI
- base PostgreSQL
- recherche vectorielle
- verification que la question concerne bien le site
- generation de la reponse

Ne mettez jamais la cle OpenAI dans le code du site public.

## Schema de fonctionnement

![Texte alternatif](SchemaFonctionnementAssistant.png "Fonctionnement du widjet")

En resume:

1. Le widget ne fait qu'afficher l'interface et envoyer les questions.
2. L'API verifie que la demande est autorisee.
3. La question est transformee en embedding.
4. PostgreSQL + pgvector cherche les passages du site les plus proches.
5. Si aucun passage n'est assez proche, l'API refuse de repondre hors sujet.
6. Si des passages sont trouves, OpenAI genere une reponse uniquement avec ce contexte.

## Prerequis

Avant d'ajouter le widget sur le site, il faut avoir:

1. Une API Agent IA deployee, par exemple:

```text
https://chat-api.votre-domaine.com
```

2. Un site cree dans l'API avec `/sites`.

3. Les pages importantes du site indexees avec `/ingest`.

4. Le domaine du site autorise dans la configuration API:

```env
SITE_ALLOWED_ORIGINS=https://www.votre-site.com
```

Si le site existe avec et sans `www`, ajoutez les deux:

```env
SITE_ALLOWED_ORIGINS=https://votre-site.com,https://www.votre-site.com
```

## Recuperer le site_id

Pour declarer un site:

```bash
curl -X POST https://chat-api.votre-domaine.com/sites \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: VOTRE_TOKEN_ADMIN' \
  -d '{"name":"Mon site","base_url":"https://www.votre-site.com"}'
```

La reponse contient un `id`:

```json
{
  "id": "c22e788c-148d-47c8-a063-35500d1906e3",
  "name": "Mon site",
  "base_url": "https://www.votre-site.com"
}
```

Gardez cet `id`: il sera utilise dans le snippet du widget.

## Indexer les pages du site

Exemple:

```bash
curl -X POST https://chat-api.votre-domaine.com/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: VOTRE_TOKEN_ADMIN' \
  -d '{
    "site_id": "c22e788c-148d-47c8-a063-35500d1906e3",
    "urls": [
      "https://www.votre-site.com/",
      "https://www.votre-site.com/services",
      "https://www.votre-site.com/contact",
      "https://www.votre-site.com/faq"
    ]
  }'
```

L'API refuse les URLs qui ne sont pas sur le domaine declare dans `base_url`.

## Generer les fichiers du widget

Depuis le projet:

```bash
cd widget
npm install
npm run build
```

Les fichiers generes sont:

```text
widget/dist/agentia-widget.iife.js
widget/dist/agentia-widget.css
```

Copiez ces fichiers dans les assets de votre site ou sur un CDN.

Exemple:

```text
https://www.votre-site.com/assets/agentia-widget.iife.js
https://www.votre-site.com/assets/agentia-widget.css
```

## Snippet a inserer sur le site

Ajoutez ce code juste avant la balise `</body>` de votre site:

```html
<link rel="stylesheet" href="/assets/agentia-widget.css">

<div id="agentia-widget"></div>

<script>
  window.AgentIAConfig = {
    apiUrl: "https://chat-api.votre-domaine.com",
    siteId: "VOTRE_SITE_ID",
    title: "Assistant"
  };
</script>

<script src="/assets/agentia-widget.iife.js"></script>
```

Remplacez:

- `https://chat-api.votre-domaine.com` par l'URL de votre API.
- `VOTRE_SITE_ID` par l'id retourne par `/sites`.
- `/assets/...` par le chemin reel des fichiers du widget.

## Exemple complet

```html
<link rel="stylesheet" href="/assets/agentia-widget.css">

<div id="agentia-widget"></div>

<script>
  window.AgentIAConfig = {
    apiUrl: "https://chat-api.monsite.com",
    siteId: "c22e788c-148d-47c8-a063-35500d1906e3",
    title: "Assistant"
  };
</script>

<script src="/assets/agentia-widget.iife.js"></script>
```

Une fois ce code ajoute, le bouton du chat apparait en bas a droite du site.

## Tester l'integration

1. Ouvrez votre site en production.
2. Ouvrez la console navigateur.
3. Verifiez qu'il n'y a pas d'erreur CORS.
4. Posez une question sur une page indexee.
5. Posez une question hors sujet, par exemple:

```text
Donne-moi une recette de tarte aux pommes
```

La reponse attendue est:

```text
Le site ne traite pas de ce sujet.
```

## Erreurs frequentes

### Le widget ne s'affiche pas

Verifiez que:

- `agentia-widget.iife.js` est bien charge.
- `agentia-widget.css` est bien charge.
- la page contient bien `<div id="agentia-widget"></div>`.
- `window.AgentIAConfig` est declare avant le script du widget.

### Erreur CORS

Ajoutez le domaine exact du site dans l'API:

```env
SITE_ALLOWED_ORIGINS=https://www.votre-site.com
```

Puis redeployez ou redemarrez l'API.

### Le widget repond toujours hors sujet

Verifiez que:

- les pages ont bien ete indexees avec `/ingest`.
- le `siteId` dans le snippet est correct.
- la question concerne vraiment une page indexee.
- `OPENAI_API_KEY` est bien configure cote API.

### Erreur 401 sur `/sites` ou `/ingest`

Le token admin manque ou est incorrect:

```http
X-Admin-Token: VOTRE_TOKEN_ADMIN
```

Ce token ne doit jamais etre expose dans le widget public.

## Configuration minimale de production

Exemple `.env` cote API:

```env
DATABASE_URL=postgresql://agent:motdepasse@postgres:5432/agentia
OPENAI_API_KEY=sk-your-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
OPENAI_CHAT_MODEL=gpt-4.1-mini
ADMIN_API_TOKEN=un-token-long-et-secret
CHAT_MAX_CONTEXT_CHUNKS=6
CHAT_MIN_RELEVANCE=0.24
CHAT_RATE_LIMIT_PER_MINUTE=20
SITE_ALLOWED_ORIGINS=https://www.votre-site.com
```
