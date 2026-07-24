# Rapport Securite OWASP

Date du rapport: 2026-07-07

Perimetre analyse:

- Backend FastAPI
- Widget Vue
- Flux d'ingestion
- Flux de chat
- Flux de reservation Google Calendar

Ce rapport ne constitue pas une certification OWASP. Il s'agit d'une revue technique du code actuel du projet, avec identification des points deja alignes avec de bonnes pratiques OWASP et des ecarts a corriger avant un usage production.

## Resume executif

Le projet applique deja plusieurs protections utiles:

- validation stricte des entrees
- requetes SQL parametrees
- restriction CORS
- rate limiting basique
- separation entre endpoints publics et endpoints d'administration

En revanche, il reste plusieurs ecarts importants qui empechent de considerer le projet comme reellement conforme a une posture OWASP production:

- authentification admin en mode fail-open si le token n'est pas configure
- risque SSRF sur l'ingestion via redirections HTTP
- protection insuffisante de l'endpoint `/chat`
- rate limiting trop faible pour un deploiement multi-instance
- gestion des secrets et valeurs par defaut trop permissive
- defenses LLM utiles mais insuffisantes comme controle de securite principal

## Points en accord

### 1. Validation des donnees d'entree

Etat: plutot en accord

Ce qui est deja bien:

- Les payloads sont valides avec Pydantic.
- Les tailles des messages et de l'historique sont bornees.
- Les roles autorises dans l'historique sont limites a `visitor|agent`.

References:

- [server/app/schemas.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/schemas.py:29)
- [server/app/schemas.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/schemas.py:34)

Pourquoi c'est positif:

- Cela reduit les risques de payloads malformes, de debordement fonctionnel, et une partie des abus applicatifs.

### 2. Requetes SQL parametrees

Etat: en accord

Ce qui est deja bien:

- Les acces base utilisent des placeholders `$1`, `$2`, etc.
- Je n'ai pas trouve de concatenation SQL directe avec des donnees utilisateur.

References:

- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py:45)
- [server/app/ingest.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/ingest.py:73)
- [server/app/retrieval.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/retrieval.py:66)

Pourquoi c'est positif:

- Cela limite fortement les risques d'injection SQL, qui font partie des categories OWASP majeures.

### 3. Restriction CORS et controle d'origine navigateur

Etat: partiellement en accord

Ce qui est deja bien:

- Les origines autorisees sont configurees explicitement.
- Une verifiation supplementaire d'origine est appliquee sur `/chat`.

References:

- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py:19)
- [server/app/security.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/security.py:37)

Pourquoi c'est positif:

- Cela reduit l'exposition accidentelle du widget a des sites non autorises dans le contexte navigateur.

Limite:

- Ce n'est pas un vrai mecanisme d'authentification applicative.

### 4. Separation entre endpoints publics et admin

Etat: conceptuellement bon, implementation insuffisante

Ce qui est deja bien:

- `/sites` et `/ingest` sont separes de `/chat`.
- Les endpoints d'administration passent par un controle dedie.

References:

- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py:43)
- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py:59)

Pourquoi c'est positif:

- C'est la bonne structure de base pour un cloisonnement des usages.

### 5. Protection basique contre l'abus

Etat: partiellement en accord

Ce qui est deja bien:

- `/chat` applique une limitation de debit par IP.

References:

- [server/app/security.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/security.py:15)

Pourquoi c'est positif:

- Cela freine les abus elementaires et les boucles d'appel triviales.

### 6. Rendu front sans injection HTML evidente

Etat: plutot en accord

Ce qui est deja bien:

- Le widget rend le contenu en interpolation Vue standard.
- Je n'ai pas vu d'usage de `v-html` pour afficher les reponses.

Pourquoi c'est positif:

- Cela limite le risque XSS DOM dans l'etat actuel du widget.

## Points a modifier

### 1. Authentification admin fail-open

Priorite: critique

Probleme:

- Si `ADMIN_API_TOKEN` est vide, les endpoints `/sites` et `/ingest` restent accessibles.
- Le controle actuel ne rejette la requete que si un token attendu existe deja.

References:

- [server/app/security.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/security.py:46)
- [server/app/config.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/config.py:16)

Risque:

- Creation de sites et ingestion non autorisees.
- Pollution de la base.
- Exposition a des appels malveillants ou a de l'ingestion de contenus non souhaites.

Solution recommandee:

- Passer en mode fail-closed.
- Refuser le demarrage de l'application si `ADMIN_API_TOKEN` est absent ou trop faible en environnement non local.

Comment faire:

1. Ajouter une validation au demarrage dans `Settings` ou `startup()` pour exiger `ADMIN_API_TOKEN`.
2. Faire echouer l'application si la variable est vide.
3. En supplement, verifier une longueur minimale raisonnable, par exemple 32 caracteres.
4. Mettre a jour `.env.example` et la documentation pour supprimer les exemples permissifs comme `change-me`.

Implementation suggeree:

- Dans `server/app/config.py`, ajouter un validateur sur `admin_api_token`.
- Ou dans `server/app/main.py`, lever une exception de configuration au demarrage si le token est vide.

Exemple de logique:

```python
if not settings.admin_api_token or len(settings.admin_api_token) < 32:
    raise RuntimeError("ADMIN_API_TOKEN must be configured with a strong value")
```

### 2. SSRF possible via redirection pendant l'ingestion

Priorite: critique

Probleme:

- L'URL initiale est verifiee contre le domaine du site.
- Mais `fetch_page()` suit les redirections HTTP automatiquement.
- Une URL autorisee peut rediriger vers une ressource interne ou sensible.

References:

- [server/app/ingest.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/ingest.py:20)
- [server/app/ingest.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/ingest.py:38)
- [server/app/ingest.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/ingest.py:59)

Risque:

- Appels serveur vers des IP privees ou services internes.
- Lecture de ressources internes via le backend.

Solution recommandee:

- Interdire les redirections hors domaine autorise.
- Bloquer les IP privees, localhost, link-local et hosts internes lors des resolutions DNS.
- Idealement, maintenir une allowlist stricte d'hotes.

Comment faire:

1. Desactiver `follow_redirects=True`.
2. Traiter les redirections manuellement.
3. A chaque `Location`, revalider le domaine de destination.
4. Resoudre le hostname et refuser les IP privees ou loopback.
5. Refuser aussi les schemas non `http` et `https`.

Implementation suggeree:

- Remplacer le `client.get(..., follow_redirects=True)` par une boucle manuelle.
- Ajouter une fonction du type `_is_safe_fetch_target(url: str) -> bool`.

Controle a ajouter:

- `127.0.0.1`
- `::1`
- plages RFC1918
- link-local
- metadata endpoints cloud si besoin

### 3. `/chat` n'a pas de vrai controle d'acces applicatif

Priorite: elevee

Probleme:

- Le controle actuel repose surtout sur CORS et l'header `Origin`.
- Une requete sans `Origin` passe.
- Un appel serveur a serveur peut donc consommer librement l'API si l'endpoint est expose.

References:

- [server/app/security.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/security.py:37)
- [server/app/main.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/main.py:68)

Risque:

- Utilisation non autorisee de l'API.
- Cout LLM non maitrise.
- Abus depuis des clients non navigateur.

Solution recommandee:

- Ajouter une authentification legere par site pour `/chat`.
- Par exemple une cle publique de site, ou mieux une signature/HMAC cote backend.

Comment faire:

Option simple:

1. Ajouter une colonne `public_api_key` par site.
2. Exiger cette cle dans le widget pour chaque appel `/chat`.
3. Verifier que `site_id` et `public_api_key` correspondent.

Option plus robuste:

1. Le widget demande un token court a un backend maitre.
2. Le token signe encode `site_id`, `origin`, expiration.
3. `/chat` verifie la signature et l'expiration.

Implementation suggeree:

- Ajouter `x-site-key` ou `Authorization: Bearer ...` sur `/chat`.
- Verifier la cle avant d'appeler le routeur LLM.

### 4. Rate limiting insuffisant pour la production

Priorite: elevee

Probleme:

- Le rate limit est en memoire locale.
- Il ne fonctionne pas correctement en multi-instance.
- Il saute au redemarrage.
- Il se base uniquement sur l'IP.

References:

- [server/app/security.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/security.py:12)
- [README.md](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/README.md:125)

Risque:

- Contournement facile a grande echelle.
- Cout LLM et degradation de service.

Solution recommandee:

- Passer a un rate limit distribue, par exemple Redis.
- Combiner plusieurs cles de limitation: IP, site_id, cle publique, eventuellement empreinte session.

Comment faire:

1. Introduire Redis.
2. Utiliser une fenetre glissante ou un token bucket.
3. Limiter au moins par `site_id + IP`.
4. Ajouter des headers de retour de type `X-RateLimit-*`.
5. Logger les depassements.

Implementation suggeree:

- Remplacer `_requests` en memoire par un stockage Redis.
- Centraliser cela dans `server/app/security.py`.

### 5. Valeurs par defaut et secrets trop permissifs

Priorite: moyenne

Probleme:

- La configuration embarque des valeurs faibles ou purement dev.
- La documentation montre encore `change-me`.
- La chaine de connexion par defaut utilise des credentials triviaux.

References:

- [server/app/config.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/config.py:11)
- [README.md](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/README.md:40)

Risque:

- Mauvaise configuration en production.
- Exposition accidentelle due au copier-coller de la doc.

Solution recommandee:

- Distinguer explicitement dev et production.
- Rendre impossibles certaines valeurs faibles hors environnement local.

Comment faire:

1. Ajouter une variable `APP_ENV=dev|prod`.
2. En `prod`, refuser:
   - token admin vide
   - mot de passe DB par defaut
   - origines localhost
3. Mettre a jour `.env.example`.
4. Mettre a jour le README avec des exemples non reutilisables.

Implementation suggeree:

- Ajouter une validation conditionnelle dans `Settings`.

### 6. Defense LLM utile mais insuffisante comme controle principal

Priorite: moyenne

Probleme:

- Le filtrage de prompt injection repose principalement sur un routeur LLM et des instructions systeme.
- Cela aide, mais ce n'est pas un mecanisme deterministe.

References:

- [server/app/openai_client.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/openai_client.py:67)
- [server/app/openai_client.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/openai_client.py:31)

Risque:

- Faux negatifs ou faux positifs.
- Dependances a un comportement de modele qui n'est pas garanti.

Solution recommandee:

- Garder la defense LLM, mais la completer par des regles applicatives deterministes.

Comment faire:

1. Definir une liste claire d'actions autorisees.
2. Refuser certaines classes de requetes avant passage au modele:
   - demandes de secrets
   - demandes de code arbitraire
   - messages clairement hors perimetre
3. Isoler les outils sensibles derriere des controles stricts cote serveur.
4. Journaliser les refus et les cas limites.

Implementation suggeree:

- Ajouter des verifications regex/regles statiques avant `route_user_message()`.
- Conserver le routeur LLM comme couche supplementaire, pas comme couche unique.

### 7. Journalisation et audit securite insuffisants

Priorite: moyenne

Probleme:

- Je n'ai pas vu de journalisation structurée des refus, abus, erreurs de securite ou operations admin.

Risque:

- Difficulte a enqueter un incident.
- Difficulte a detecter un abus progressif.

Solution recommandee:

- Ajouter des logs structures pour les evenements critiques.

Comment faire:

1. Logger les acces admin.
2. Logger les refus d'origine.
3. Logger les depassements de rate limit.
4. Logger les erreurs d'ingestion et les redirections refusees.
5. Eviter de logger le contenu complet des messages si cela expose des donnees personnelles.

Implementation suggeree:

- Ajouter un logger central.
- Emettre des evenements JSON avec timestamp, endpoint, site_id, IP, decision, motif.

## Priorisation recommandee

### A corriger immediatement

1. Auth admin fail-open
2. SSRF sur ingestion
3. Vrai controle d'acces sur `/chat`

### A corriger ensuite

1. Rate limiting distribue
2. Durcissement des secrets et de la configuration prod
3. Journalisation securite

### A ameliorer en continu

1. Regles deterministes supplementaires autour du LLM
2. Revue de dependances
3. Tests de securite automatises plus complets

## Conclusion

Le projet n'est pas actuellement "conforme OWASP production". Il est en revanche sur une base saine pour evoluer vite vers une posture plus solide.

Le plus important est de ne pas confondre garde-fous presents et niveau de securite suffisant. Aujourd'hui, la validation d'entree et la structure applicative sont bonnes, mais les controles d'acces, l'ingestion distante et la protection de l'API publique doivent etre durcis avant de pouvoir revendiquer un alignement serieux avec les principes OWASP.
