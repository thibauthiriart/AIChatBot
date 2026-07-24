# Flux offres avec contexte client, taches de rapports et juge LLM

Cette note documente le comportement attendu du module de propositions d'offres quand l'utilisateur demarre un travail a partir d'un client existant.

## Objectif

Quand l'utilisateur dit:

```text
On va bosser sur le projet de Guillaume
```

l'agent doit:

1. reconnaitre le client dans la base;
2. regarder les projets rattaches a ce client;
3. demander quel projet utiliser s'il y en a plusieurs;
4. charger le contexte du projet choisi;
5. afficher les taches issues des rapports/comptes rendus;
6. laisser l'utilisateur classer ces taches:
   - dans l'offre;
   - plus tard;
   - oubliees;
7. generer un brouillon d'offre qui ne retient que les taches classees `dans l'offre`.

## Donnees utilisees

Le flux s'appuie sur les tables de memoire client:

- `clients`
- `client_projects`
- `client_artifacts`
- `client_events`
- `client_project_tasks`

Les taches proposees a l'utilisateur viennent uniquement de `client_project_tasks`.

Les taches internes de production d'offre, par exemple generer le brouillon, valider le perimetre ou exporter le document, sont volontairement exclues de la liste a classer. Le code correspondant est conserve en commentaire dans [server/app/offer_service.py](/Users/thibauthiriart/PycharmProjects/AgentIAConversation/server/app/offer_service.py:1058) pour pouvoir etre reactive plus tard, mais il ne doit pas etre utilise dans le flux actuel.

## Persistance cote offres

Le choix utilisateur est stocke dans:

```text
offer_project_task_choices
```

Cette table contient une ligne par tache candidate pour un projet d'offre:

- `project_id`: projet d'offre;
- `task_key`: cle stable, par exemple `client:<task_id>`;
- `title`: titre de la tache;
- `detail`: detail court;
- `source`: actuellement `client`;
- `source_id`: identifiant de la tache source;
- `decision`: `pending`, `include`, `later` ou `forgotten`.

Les valeurs fonctionnelles exposees a l'utilisateur sont:

- `include` -> `dans l'offre`;
- `later` -> `plus tard`;
- `forgotten` -> `oubliee`;
- `pending` -> `a choisir`.

## Parcours conversationnel

### 1. Creation du projet d'offre

Le frontend appelle:

```text
POST /offers/projects
```

Le backend cree une ligne dans `offer_projects` et un premier message agent.

### 2. Message client

L'utilisateur envoie:

```text
On va bosser sur le projet de Guillaume
```

Le backend passe par:

- `_maybe_select_linked_client_project(...)`
- `_maybe_link_client_from_message(...)`

Si le client a plusieurs projets, l'agent repond avec une liste numerotee:

```text
J'ai trouve plusieurs projets pour Guillaume. Lequel doit servir de contexte pour cette proposition ?
1. ...
2. ...
Repondez avec le numero ou le nom du projet.
```

### 3. Choix du projet

L'utilisateur repond avec un numero ou un nom de projet.

Le backend:

1. lie `offer_projects.linked_client_id`;
2. lie `offer_projects.linked_client_project_id`;
3. charge les comptes rendus/documents du projet;
4. charge les evenements/reunions du projet;
5. charge les taches du projet;
6. synchronise ces taches dans `offer_project_task_choices`;
7. affiche la liste a classer.

Exemple de reponse:

```text
Contexte charge pour Guillaume / projet E2E Offre - Portail Client.
- Comptes rendus/documents charges : 1
- Reunions/evenements charges : 0
- Taches existantes chargees : 3

Voici les taches a classer pour cette proposition :
- T1 - Envoyer les acces de preproduction [...]
- T2 - Preparer les contenus de la page d'accueil [...]
- T3 - Valider le cahier des charges final [...]

Dites-moi lesquelles mettre dans l'offre, laisser pour plus tard ou oublier.
```

### 4. Classement des taches

L'utilisateur peut ecrire:

```text
dans l'offre T1, plus tard T2, oublier T3
```

Le backend enregistre:

- `T1` -> `include`;
- `T2` -> `later`;
- `T3` -> `forgotten`.

La reponse confirme le classement:

```text
C'est note pour les taches de la proposition :
- dans l'offre : T1
- plus tard : T2
- oubliee : T3

Je prendrai uniquement les taches marquees 'dans l'offre' dans la section taches du brouillon.
```

### 5. Generation du brouillon

Le frontend appelle:

```text
POST /offers/projects/{project_id}/generate
```

La generation utilise:

- les champs de cadrage de l'offre;
- les references d'offres;
- les profils equipe;
- le contexte client/projet charge;
- les decisions de `offer_project_task_choices`.

Dans le Markdown genere, la section:

```text
### Taches retenues dans l'offre
```

ne contient que les taches dont `decision = include`.

Les taches classees `later` ou `forgotten` ne doivent pas apparaitre dans cette section.

## Test end-to-end avec LLM-as-judge

Le script de test est:

```text
tests/run_offer_e2e_llm_judge.py
```

Il simule un usage complet de l'application via `TestClient` FastAPI.

### Ce que fait le test

1. Cherche en base un client existant avec au moins un compte rendu et des taches.
2. Prepare deux projets pour ce client afin de forcer la question "quel projet ?".
3. Rattache un compte rendu de test au projet principal.
4. Rattache trois taches issues de ce compte rendu.
5. Cree un projet d'offre.
6. Envoie un message utilisateur: `On va bosser sur le projet de <client>`.
7. Verifie que l'agent demande le projet.
8. Repond avec le projet.
9. Verifie que le contexte et les taches sont charges.
10. Classe les taches: `dans l'offre T1, plus tard T2, oublier T3`.
11. Genere le brouillon.
12. Verifie de maniere deterministe que seule `T1` est dans la section des taches retenues.
13. Envoie le scenario a un LLM juge si `OPENAI_API_KEY` est configure.

### Commande

```bash
.venv/bin/python tests/run_offer_e2e_llm_judge.py
```

Le test a besoin de:

- PostgreSQL local accessible via `DATABASE_URL`;
- les dependances installees dans `.venv`;
- `OPENAI_API_KEY` pour activer le juge LLM.

Si `OPENAI_API_KEY` n'est pas configure, la partie juge LLM est ignoree, mais les checks deterministes restent executes.

### Criteres deterministes

Le test verifie notamment:

- l'agent demande le projet si plusieurs projets existent;
- le contexte est charge apres le choix;
- la liste de taches est affichee;
- les taches viennent des rapports/projets client;
- la decision `dans l'offre T1` est persistee;
- le brouillon contient la tache incluse;
- le brouillon exclut les taches `plus tard` et `oubliees` de la section des taches retenues.

### Juge LLM

Le juge recoit:

- le scenario attendu;
- les checks deterministes;
- les reponses agent;
- le Markdown genere.

Il doit repondre en JSON avec:

- `overall`: note de 1 a 5;
- `passed`: booleen;
- `strengths`;
- `weaknesses`;
- `summary`.

Lors du dernier run connu, le juge a retourne:

```json
{
  "overall": 5,
  "passed": true
}
```

## Tests unitaires associes

Les tests unitaires principaux sont dans:

```text
tests/test_offer_service.py
```

Ils couvrent notamment:

- extraction de reponses courtes;
- selection du projet par numero ou par nom;
- detection des decisions de taches;
- inclusion dans le brouillon uniquement des taches classees `dans l'offre`;
- exclusion des taches internes `offer:*` de la liste a classer.

Commande:

```bash
.venv/bin/python -m unittest tests.test_offer_service
```

## Points d'attention

- La numerotation `T1`, `T2`, `T3` depend de l'ordre retourne par la base pour les taches du projet. Les tests end-to-end lisent donc le mapping affiche par l'agent avant d'asserter le brouillon.
- Le flux est encore majoritairement deterministe. Le LLM intervient ici comme juge QA, pas comme moteur principal de generation des decisions.
- Les taches `plus tard` et `oubliees` restent stockees dans `offer_project_task_choices`; elles sont seulement exclues de la section des taches retenues dans l'offre.
