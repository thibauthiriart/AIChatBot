# Documentation backend

Cette page explique comment le backend fonctionne aujourd'hui, avec un focus sur:

- le chat documentaire,
- la logique de rendez-vous,
- la logique de propositions d'offres,
- la structure de la base,
- le lien entre frontend et backend.

Le point d'entree principal est [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py).

## 1. Vue d'ensemble

Le backend repose sur:

- `FastAPI` pour exposer les routes HTTP,
- `PostgreSQL` pour stocker le contenu et les donnees metier,
- `asyncpg` pour les acces SQL,
- `OpenAI` pour le routage et la generation des reponses documentaires,
- quelques services metier Python dedies: chat, booking, Noota, Drive, offres.

En pratique, le backend ne fonctionne pas comme un seul "agent" monolithique. Il y a plusieurs flux:

1. un flux `chat` general,
2. un flux `booking` pour les rendez-vous,
3. un flux `noota / drive` pour les comptes rendus,
4. un flux `offers` pour les propositions d'offres.

Chaque flux a ses propres regles et ses propres routes.

## 2. Demarrage de l'application

Au `startup`, l'application:

- ouvre le pool PostgreSQL,
- verifie et cree les tables utiles si elles n'existent pas,
- initialise les schemas de memoire client,
- initialise les schemas Noota / Drive,
- initialise les schemas `offers`,
- s'assure qu'un scope par defaut existe dans `sites`.

Cela se passe dans:

- [server/app/db.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/db.py)
- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py)

La configuration est centralisee dans [server/app/config.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/config.py).

Les variables importantes sont:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL`
- `OPENAI_ROUTER_MODEL`
- `SITE_ALLOWED_ORIGINS`
- `GOOGLE_CALENDAR_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `SMTP_*`

## 3. Structure generale des donnees

Le backend utilise plusieurs familles de tables.

### 3.1 Base documentaire

Tables principales:

- `sites`
- `documents`
- `chunks`

But:

- stocker les pages indexees,
- decouper les contenus en blocs,
- alimenter la recherche textuelle du chat.

Le schema initial est visible dans [sql/init.sql](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/sql/init.sql).

### 3.2 Memoire client

Tables principales:

- `clients`
- `client_projects`
- `client_artifacts`
- `client_events`

But:

- stocker le contexte CRM / projet / notes / comptes rendus,
- enrichir le chat avec un contexte client plus precis.

Le code associe est dans [server/app/client_memory.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/client_memory.py).

### 3.3 Rendez-vous

Tables principales:

- `appointment_notifications`
- `appointment_schedule_logs`

But:

- journaliser les rendez-vous confirmes,
- garder une trace des tentatives de planification.

### 3.4 Domaine offres

Tables principales ajoutees pour la partie propositions d'offres:

- `offer_projects`
- `offer_project_messages`
- `offer_project_emails`
- `offer_reference_documents`
- `team_profiles`
- `offer_project_exports`

But:

- stocker les projets d'offre,
- stocker l'historique du chat d'offre,
- stocker les emails colles manuellement,
- stocker les anciennes offres de reference,
- stocker les profils equipe,
- stocker les fichiers generes.

Le code associe est dans [server/app/offer_service.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/offer_service.py).

## 4. Comment fonctionne le chat documentaire

La route principale est:

```text
POST /chat
```

Le flux complet est le suivant.

### 4.1 Validation et securite

Le backend valide le payload avec les modeles Pydantic de [server/app/schemas.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/schemas.py).

Ensuite il applique:

- controle d'origine,
- rate limiting,
- verification du `site_id` ou du scope par defaut.

### 4.2 Routage du message

Le backend appelle `route_user_message(...)` dans [server/app/openai_client.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/openai_client.py).

Ce prompt de routage classe le message en:

- `greeting`
- `knowledge`
- `appointment`
- `deny`

Important:

- ce prompt est commun au systeme,
- il ne redige pas la reponse finale,
- il sert seulement a choisir le bon flux.

### 4.3 Cas rendez-vous

Si la categorie retournee est `appointment`, le backend ne continue pas dans le chat documentaire.

Il bascule vers `BookingService.handle_message(...)` dans [server/app/booking.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/booking.py).

### 4.4 Cas connaissance

Si la categorie retournee est `knowledge`, le backend:

1. reformule la question avec `rewrite_user_message(...)`,
2. recupere des blocs documentaires avec `retrieve_context(...)`,
3. tente de retrouver un client cible avec `resolve_client_for_chat(...)`,
4. si un client est reconnu, injecte son contexte via `retrieve_client_context(...)`,
5. sinon peut injecter un contexte global recent via `retrieve_recent_global_context(...)`,
6. appelle `generate_answer(...)` pour produire la reponse finale.

Le systeme prompt de `generate_answer(...)` impose:

- repondre seulement a partir du contexte,
- ne pas inventer,
- rester en texte brut,
- refuser implicitement si le contexte est insuffisant.

### 4.5 Recherche documentaire

La recherche actuelle n'est pas vectorielle.

Le backend charge les `chunks` et les score avec une logique lexicale:

- mots-cles,
- bigrammes,
- correspondance du texte normalise.

Cette logique est dans [server/app/retrieval.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/retrieval.py).

## 5. Comment fonctionne la logique de rendez-vous

Le booking est pilote principalement par du code Python, pas par un prompt de conversation riche.

Le fichier central est [server/app/booking.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/booking.py).

Le flux est:

1. extraire nom, email, date, heure, fuseau, confirmation depuis les messages,
2. verifier les champs manquants,
3. appeler Google Calendar pour lire les disponibilites,
4. proposer des creneaux,
5. confirmer le creneau choisi,
6. creer l'evenement Google Calendar,
7. journaliser la reservation.

Important:

- le rendez-vous n'a pas aujourd'hui de prompt LLM dedie complet,
- il utilise surtout du parsing deterministic,
- le LLM intervient surtout dans le routage amont.

## 6. Comment fonctionne la logique offres

La logique offres repose sur des routes dediees et un service dedie.

### 6.1 Routes principales

Routes exposees dans [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py):

- `GET /offers/projects`
- `POST /offers/projects`
- `PATCH /offers/projects/{project_id}`
- `DELETE /offers/projects/{project_id}`
- `GET /offers/projects/{project_id}/context`
- `POST /offers/projects/{project_id}/messages`
- `POST /offers/projects/{project_id}/emails`
- `POST /offers/projects/{project_id}/generate`
- `POST /offers/projects/{project_id}/exports/{export_format}`
- `GET /offers/projects/{project_id}/exports/{export_id}/download`
- `POST /offers/references`
- `POST /offers/team-profiles`

### 6.2 Creation d'un projet d'offre

Quand on cree un projet:

1. une ligne est ajoutee dans `offer_projects`,
2. un premier message agent est ajoute dans `offer_project_messages`,
3. le projet apparait ensuite dans la page frontend.

### 6.3 Contexte d'un projet

Quand le frontend appelle:

```text
GET /offers/projects/{project_id}/context
```

le backend renvoie:

- les infos du projet,
- les messages,
- les emails rattaches,
- les references d'offres rapprochees,
- les profils equipe suggeres,
- la checklist des informations manquantes,
- les exports deja generes,
- le brouillon d'offre si deja produit.

### 6.4 Detection des informations manquantes

Le service offres definit une liste de champs attendus:

- client,
- besoin,
- perimetre,
- livrables,
- planning,
- prix,
- temps passe,
- equipe,
- contraintes.

La checklist est construite a partir de ces champs.

Aujourd'hui, cette logique est principalement reglee par:

- `_FIELD_DEFINITIONS`
- `_build_missing_items(...)`

dans [server/app/offer_service.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/offer_service.py).

### 6.5 Messages offres

Quand le frontend envoie un message sur un projet d'offre:

```text
POST /offers/projects/{project_id}/messages
```

le backend:

1. stocke le message visiteur,
2. tente d'extraire des updates simples,
3. met a jour le projet si des infos ont ete reconnues,
4. reconstruit la checklist des manques,
5. repond avec un message agent guide.

Important:

- ce flux n'utilise pas encore un prompt LLM specialise dedie aux offres,
- la logique actuelle est surtout metier et reglee par code,
- la reponse est construite a partir des champs manquants et des demandes detectees.

### 6.6 Matching des references et de l'equipe

Le backend cherche ensuite:

- des offres de reference proches,
- des profils equipe pertinents.

Ce matching est lexical:

- titre,
- secteur,
- besoin,
- contenu,
- mots-cles.

Il n'y a pas encore de retrieval vectoriel pour la partie offres.

### 6.7 Generation du brouillon

Quand le frontend appelle:

```text
POST /offers/projects/{project_id}/generate
```

le backend:

1. recharge le projet,
2. recupere references et profils equipe,
3. compose un document Markdown structure,
4. stocke ce brouillon dans `offer_projects.generated_offer_markdown`,
5. passe le projet au statut `ready`.

La construction actuelle est faite dans `_build_offer_markdown(...)`.

### 6.8 Exports

Le backend sait ensuite generer:

- un `DOCX`
- un `PDF`

Le flux est:

1. le frontend appelle `POST /offers/projects/{project_id}/exports/docx` ou `/pdf`,
2. le backend rend le fichier,
3. il stocke le binaire dans `offer_project_exports`,
4. le frontend telecharge ensuite via la route `/download`.

Les fonctions de rendu sont:

- `_build_docx(...)`
- `_build_pdf(...)`

dans [server/app/offer_service.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/offer_service.py).

Important:

- l'export est fonctionnel,
- mais ce n'est pas encore un moteur de template commercial avance.

## 7. Prompt et "agents": ce qui est partage et ce qui est different

Il est utile de distinguer trois niveaux.

### 7.1 Prompt partage

Le prompt de routage dans [server/app/openai_client.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/openai_client.py) est partage.

Il sert a dire:

- ceci est un message de connaissance,
- ceci est un message de rendez-vous,
- ceci est un message a refuser.

### 7.2 Chat documentaire

Le chat documentaire a son propre prompt de generation dans `generate_answer(...)`.

Ce prompt est strictement base sur le contexte retrouve.

### 7.3 Booking

Le booking n'a pas aujourd'hui un grand prompt LLM dedie.

Il utilise principalement du code Python metier.

### 7.4 Offres

La partie offres a aujourd'hui un flux metier dedie, mais pas encore un vrai prompt LLM dedie separé.

Autrement dit:

- il y a bien une logique offre differente,
- mais pas encore un `offer_system_prompt` riche et specialise.

## 8. Comment le frontend consomme ce backend

La page principale frontend est geree par [frontend/src/App.vue](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/frontend/src/App.vue).

L'etat global est concentre dans [frontend/src/composables/useAgentiaState.ts](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/frontend/src/composables/useAgentiaState.ts).

### 8.1 Dashboard / chat classique

Le frontend appelle:

- `/chat`
- `/appointments/recent`
- `/integrations/noota/google-drive/...`

### 8.2 Page offres

Le frontend appelle:

- `/offers/projects`
- `/offers/projects/{id}/context`
- `/offers/projects/{id}/messages`
- `/offers/projects/{id}/emails`
- `/offers/projects/{id}/generate`
- `/offers/projects/{id}/exports/{format}`

La vue dediee est [frontend/src/components/OfferProposalsView.vue](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/frontend/src/components/OfferProposalsView.vue).

Le flux detaille "client -> projet -> contexte -> taches de rapports -> choix utilisateur -> brouillon", ainsi que le test end-to-end avec juge LLM, est documente dans [docs/offer-proposals-client-context-e2e.md](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/docs/offer-proposals-client-context-e2e.md).

## 9. Limites actuelles

Les principales limites actuelles sont:

- la recherche documentaire est lexicale, pas vectorielle,
- la logique offres est surtout reglee par code, pas encore par un agent LLM specialise,
- les emails d'offre sont colles manuellement, pas synchronises depuis Gmail,
- le matching des references et des profils est simple,
- l'export DOCX/PDF est technique et fonctionnel, mais pas encore mis en forme comme une vraie trame commerciale.

## 10. Evolutions naturelles

Les prochaines evolutions logiques seraient:

1. ajouter un vrai prompt dedie `offer_system_prompt`,
2. faire un retrieval plus robuste sur les offres de reference,
3. ajouter un vrai template de marque pour les exports,
4. permettre un back-office d'administration des references et profils equipe,
5. mieux structurer l'extraction des informations manquantes.

## 11. Fichiers a lire en priorite

Pour comprendre rapidement le projet, lire dans cet ordre:

1. [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py)
2. [server/app/openai_client.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/openai_client.py)
3. [server/app/retrieval.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/retrieval.py)
4. [server/app/client_memory.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/client_memory.py)
5. [server/app/booking.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/booking.py)
6. [server/app/offer_service.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/offer_service.py)
7. [frontend/src/composables/useAgentiaState.ts](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/frontend/src/composables/useAgentiaState.ts)
