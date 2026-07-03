# Mise en place des tokens et de Google Calendar

Ce document decrit les secrets et variables d'environnement necessaires pour faire tourner le projet, puis la configuration complete de Google Calendar pour la prise de rendez-vous.

## Vue d'ensemble

Le projet utilise deux familles de credentials:

- les credentials LLM pour le routage et les reponses
- les credentials Google pour lire les disponibilites et creer des rendez-vous

Le fichier central de configuration locale est `.env`.

Un point important:

- `GOOGLE_API_KEY` n'est pas utilisee par ce projet pour la reservation
- la reservation Google Calendar repose sur un fichier `service account JSON`

## Variables d'environnement principales

Exemple de base:

```env
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentia

OPENAI_API_KEY=...
OPENAI_BASE_URL=
OPENAI_ROUTER_MODEL=gpt-4.1-mini
OPENAI_CHAT_MODEL=moonshotai/kimi-k2.5

ADMIN_API_TOKEN=change-me

CHAT_MAX_CONTEXT_CHUNKS=6
CHAT_RATE_LIMIT_PER_MINUTE=20
SITE_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8080

BOOKING_PROVIDER=google_calendar
BOOKING_TIMEZONE_DEFAULT=Europe/Paris
BOOKING_SLOT_DURATION_MINUTES=30
BOOKING_MAX_SUGGESTIONS=3
BOOKING_WORKDAY_START_HOUR=9
BOOKING_WORKDAY_END_HOUR=17
BOOKING_EVENT_SUMMARY=Premier rendez-vous

GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/google-service-account.json
GOOGLE_SERVICE_ACCOUNT_SUBJECT=
```

## Tokens et secrets du projet

### `OPENAI_API_KEY`

Utilisation:

- obligatoire pour le routeur LLM
- obligatoire pour la generation de reponse

Sources possibles:

- cle OpenAI standard
- cle Vercel AI Gateway si `OPENAI_BASE_URL` pointe vers Vercel

Exemples:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=
```

ou

```env
OPENAI_API_KEY=vercel_xxx
OPENAI_BASE_URL=https://ai-gateway.vercel.sh/v1
```

### `ADMIN_API_TOKEN`

Utilisation:

- protege `POST /sites`
- protege `POST /ingest`

Recommendation:

- utiliser une valeur longue et non triviale en production

Exemple:

```env
ADMIN_API_TOKEN=change-me-to-a-long-random-secret
```

### `DATABASE_URL`

Utilisation:

- connexion PostgreSQL
- necessaire pour le stockage des sites, sources et embeddings

Exemple local:

```env
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentia
```

### `SITE_ALLOWED_ORIGINS`

Utilisation:

- whitelist CORS pour le widget et les appels frontend vers `/chat`

Exemple:

```env
SITE_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8080,https://votre-site.fr
```

## Variables Google Calendar

### `BOOKING_PROVIDER`

Valeur actuelle supportee:

```env
BOOKING_PROVIDER=google_calendar
```

### `GOOGLE_CALENDAR_ID`

C'est l'identifiant du calendrier cible.

Ou le trouver:

1. Ouvrir Google Calendar
2. Choisir le calendrier
3. Ouvrir `Parametres et partage`
4. Aller a `Integrer l'agenda`
5. Copier `ID de l'agenda`

Exemples:

- agenda principal: souvent l'email Google, par exemple `prenom.nom@gmail.com`
- agenda secondaire: souvent une valeur du type `abc123@group.calendar.google.com`

### `GOOGLE_SERVICE_ACCOUNT_FILE`

C'est le chemin absolu vers le fichier JSON du compte de service Google.

Exemple:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=/Users/vous/Downloads/google-calendar-service-account.json
```

### `GOOGLE_SERVICE_ACCOUNT_SUBJECT`

Laisser vide dans le cas standard.

Cette variable ne sert que si vous utilisez une delegation `Domain-Wide Delegation` dans un Google Workspace.

Exemple:

```env
GOOGLE_SERVICE_ACCOUNT_SUBJECT=
```

ou

```env
GOOGLE_SERVICE_ACCOUNT_SUBJECT=user@votre-domaine.com
```

## Mise en place Google Calendar

### 1. Activer l'API Google Calendar

Dans Google Cloud Console:

1. Creer ou choisir un projet
2. Ouvrir `APIs & Services`
3. Activer `Google Calendar API`

### 2. Creer un compte de service

Dans Google Cloud Console:

1. Aller dans `IAM et administration`
2. Ouvrir `Comptes de service`
3. Cliquer sur `Creer un compte de service`
4. Donner un nom, par exemple `calendar-chatbot`
5. Valider

### 3. Generer le fichier JSON

1. Ouvrir le compte de service cree
2. Aller dans l'onglet `Clés`
3. `Ajouter une clé`
4. `Créer une nouvelle clé`
5. Choisir `JSON`
6. Telecharger le fichier

Le fichier JSON contient notamment:

- `type`
- `project_id`
- `client_email`
- `private_key`

Le champ critique pour le partage du calendrier est:

```json
"client_email": "votre-compte@votre-projet.iam.gserviceaccount.com"
```

### 4. Partager le calendrier avec le compte de service

Dans Google Calendar:

1. Ouvrir le calendrier cible
2. Aller dans `Parametres et partage`
3. Ouvrir `Partager avec des personnes ou groupes`
4. Ajouter l'adresse `client_email` du compte de service
5. Donner au minimum le droit `Apporter des modifications aux evenements`

Sans ce partage:

- la lecture des disponibilites peut echouer
- ou la creation d'evenement peut echouer

### 5. Renseigner `.env`

Exemple:

```env
BOOKING_PROVIDER=google_calendar
GOOGLE_CALENDAR_ID=thibaut.hiriart@gmail.com
GOOGLE_SERVICE_ACCOUNT_FILE=/Users/thibauthiriart/PycharmProjects/AgentIAConversation/google-service-account.json
GOOGLE_SERVICE_ACCOUNT_SUBJECT=
```

### 6. Installer les dependances Python

Le provider Google repose notamment sur:

- `google-auth`
- `requests`
- `httpx`

Installation:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Verifications

### Verifier le token Google

Script:

```bash
.venv/bin/python tests/check_google_calendar_config.py
```

Resultat attendu:

```text
google_access_token_ok True
```

### Verifier la lecture des disponibilites

Script:

```bash
.venv/bin/python tests/check_google_calendar_slots.py
```

Ce script liste des creneaux libres reels du calendrier configure.

### Verifier le flux conversationnel complet

Script:

```bash
.venv/bin/python tests/run_chat_booking_flow.py
```

Ce script simule une conversation complete:

- intention de reservation
- collecte des informations
- proposition de creneaux
- confirmation
- creation du rendez-vous

## Point important sur les comptes de service

Avec un compte de service Google standard:

- la lecture des disponibilites fonctionne
- la creation d'un evenement dans le calendrier partage fonctionne
- l'invitation automatique d'attendees externes peut etre refusee par Google

Erreur typique:

```text
forbiddenForServiceAccounts
Service accounts cannot invite attendees without Domain-Wide Delegation of Authority.
```

Dans ce projet, le provider est donc configure ainsi:

- creation de l'evenement sans `attendees` par defaut
- ajout des `attendees` uniquement si `GOOGLE_SERVICE_ACCOUNT_SUBJECT` est configure dans un contexte compatible

Consequence:

- le rendez-vous est bien cree dans le calendrier
- mais un email d'invitation n'est pas necessairement envoye au visiteur dans le mode standard

## Bonnes pratiques de securite

- ne jamais committer un vrai fichier `service-account.json`
- ne jamais laisser une `private_key` trainer dans le repo
- si une cle JSON a ete exposee, la revoquer et en regenerer une nouvelle
- ne pas partager `OPENAI_API_KEY`, `ADMIN_API_TOKEN` ou le JSON de service account
- utiliser un `.env` distinct par environnement

## Checklist rapide

- `OPENAI_API_KEY` renseignee
- `OPENAI_BASE_URL` correcte si gateway externe
- `ADMIN_API_TOKEN` change
- PostgreSQL disponible
- `BOOKING_PROVIDER=google_calendar`
- `GOOGLE_CALENDAR_ID` renseigne
- `GOOGLE_SERVICE_ACCOUNT_FILE` renseigne
- calendrier partage avec le `client_email` du service account
- `tests/check_google_calendar_config.py` retourne `True`
- `tests/check_google_calendar_slots.py` retourne des creneaux

