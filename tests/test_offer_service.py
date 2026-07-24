from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

with patch.dict(
    "sys.modules",
    {
        "server.app.db": SimpleNamespace(db=object()),
    },
):
    from server.app.offer_service import (
        _NO_CONSTRAINTS_ANSWER,
        _build_offer_markdown,
        _build_offer_task_candidates,
        _build_offer_task_review,
        _extract_task_ids_for_decision,
        _extract_updates_from_message,
        _field_from_prompted_message,
        is_offer_later_task_lookup_request,
        _is_offer_task_request,
        _select_project_from_message,
        _summarize_offer_task_decision,
    )


class OfferProjectMessageExtractionTests(unittest.TestCase):
    def test_accepts_short_negative_reply_for_constraints(self) -> None:
        missing_items = [
            {
                "key": "constraints",
                "status": "missing",
                "priority": "important",
            }
        ]

        updates = _extract_updates_from_message("non", missing_items)

        self.assertEqual(updates, {"constraints": _NO_CONSTRAINTS_ANSWER})

    def test_short_negative_reply_does_not_fill_other_missing_fields(self) -> None:
        missing_items = [
            {
                "key": "pricing_details",
                "status": "missing",
                "priority": "critical",
            }
        ]

        updates = _extract_updates_from_message("non", missing_items)

        self.assertEqual(updates, {})

    def test_accepts_negative_reply_when_last_prompt_asked_constraints(self) -> None:
        missing_items = [
            {
                "key": "pricing_details",
                "status": "missing",
                "priority": "critical",
            }
        ]

        updates = _extract_updates_from_message("non", missing_items, "constraints")

        self.assertEqual(updates, {"constraints": _NO_CONSTRAINTS_ANSWER})

    def test_detects_constraints_prompt_from_last_agent_message(self) -> None:
        messages = [
            {
                "role": "agent",
                "content": "Y a-t-il des contraintes, hypotheses ou exclusions a faire apparaitre ?",
            },
            {
                "role": "visitor",
                "content": "non",
            },
        ]

        self.assertEqual(_field_from_prompted_message(messages), "constraints")

    def test_detects_offer_task_request(self) -> None:
        self.assertTrue(_is_offer_task_request("au niveau des taches on a quoi"))

    def test_builds_offer_task_review_with_choices(self) -> None:
        project = {
            "request_summary": "Refonte de l'espace client",
            "scope_details": "Cadrage, UX et implementation",
            "deliverables": "Maquettes et application",
            "planning_details": "Lot 1 en septembre",
            "pricing_details": "Forfait 20k",
            "time_spent_details": "25 jours",
            "team_details": "Chef de projet et developpeur",
            "constraints": "Aucune contrainte",
        }

        answer = _build_offer_task_review(project)

        self.assertIn("T1", answer)
        self.assertIn("T8", answer)
        self.assertIn("garder T1 T3, plus tard T2, retirer T4", answer)

    def test_summarizes_offer_task_decision(self) -> None:
        answer = _summarize_offer_task_decision("garder T1 T3, plus tard T2, retirer T4")

        self.assertIn("A garder : T1, T3", answer)
        self.assertIn("A faire plus tard : T2", answer)
        self.assertIn("A retirer : T4", answer)

    def test_selects_client_project_by_number(self) -> None:
        projects = [
            {"id": "p1", "name": "Migration CRM"},
            {"id": "p2", "name": "Refonte portail"},
        ]

        self.assertEqual(_select_project_from_message("le 2", projects), projects[1])

    def test_selects_client_project_by_name(self) -> None:
        projects = [
            {"id": "p1", "name": "Migration CRM"},
            {"id": "p2", "name": "Refonte portail"},
        ]

        self.assertEqual(_select_project_from_message("on part sur la refonte portail", projects), projects[1])

    def test_extracts_task_ids_before_and_after_offer_marker(self) -> None:
        markers = ("dans l'offre", "dans l offre", "inclure", "inclu", "mettre", "mets", "garde", "garder", "conserve")

        self.assertEqual(_extract_task_ids_for_decision("dans l'offre t1 t3, plus tard t2", markers), ["T1", "T3"])
        self.assertEqual(_extract_task_ids_for_decision("t1 t3 dans l'offre, plus tard t2", markers), ["T1", "T3"])

    def test_offer_markdown_only_lists_included_task_choices(self) -> None:
        project = {
            "title": "Refonte",
            "client_name": "Mme Michu",
            "request_summary": "Refonte portail",
            "scope_details": "Implementation",
            "deliverables": "Application",
            "team_details": "Equipe projet",
            "planning_details": "Septembre",
            "pricing_details": "20k",
            "time_spent_details": "25 jours",
            "constraints": "Aucune",
        }
        markdown = _build_offer_markdown(
            project,
            [],
            [],
            {"artifacts": [], "events": [], "tasks": []},
            [
                {"title": "Atelier cadrage", "detail": "client", "decision": "include"},
                {"title": "Migration archive", "detail": "plus tard", "decision": "later"},
            ],
        )

        selected_section = markdown.split("### Etat de reference des taches", 1)[0]
        self.assertIn("Atelier cadrage", selected_section)
        self.assertNotIn("Migration archive", selected_section)

    def test_offer_markdown_regeneration_uses_previous_offer_as_source_of_truth(self) -> None:
        project = {
            "title": "Refonte",
            "client_name": "Mme Michu",
            "request_summary": "Nouveau resume qui ne doit pas remplacer la base",
            "scope_details": "Nouveau perimetre",
            "deliverables": "Nouveaux livrables",
            "team_details": "Equipe projet",
            "planning_details": "Septembre",
            "pricing_details": "20k",
            "time_spent_details": "25 jours",
            "constraints": "Aucune",
        }
        previous = "# Proposition d'offre - Refonte\n\n## Contexte et besoin\nVersion validee par le client"

        markdown = _build_offer_markdown(
            project,
            [],
            [],
            {"artifacts": [], "events": [], "tasks": []},
            [
                {"title": "Atelier cadrage", "detail": "a inclure", "decision": "include"},
                {"title": "Migration archive", "detail": "hors lot", "decision": "later"},
            ],
            previous_offer_markdown=previous,
        )

        self.assertTrue(markdown.startswith(previous))
        self.assertIn("## Etat actuel des taches du projet", markdown)
        self.assertIn("Atelier cadrage", markdown)
        self.assertIn("Migration archive", markdown)
        self.assertNotIn("Nouveau resume qui ne doit pas remplacer la base", markdown)

    def test_offer_task_candidates_only_use_report_tasks(self) -> None:
        project = {
            "request_summary": "Refonte portail",
            "scope_details": "Implementation",
            "deliverables": "Application",
            "planning_details": "Septembre",
            "pricing_details": "20k",
            "time_spent_details": "25 jours",
            "team_details": "Equipe projet",
            "constraints": "Aucune",
        }
        candidates = _build_offer_task_candidates(
            project,
            {
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Preparer le cadrage",
                        "owner": "Alice",
                        "due_date": "2026-08-01",
                        "source_excerpt": "Action issue du compte rendu",
                    }
                ]
            },
        )

        self.assertEqual([item["task_key"] for item in candidates], ["client:task-1"])

    def test_offer_task_candidates_surface_repeated_report_mentions(self) -> None:
        candidates = _build_offer_task_candidates(
            {},
            {
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Synchronisation Teams",
                        "owner": "",
                        "due_date": "",
                        "source_excerpt": "Le client souhaite synchroniser les notifications Teams",
                        "report_mentions": 3,
                    }
                ]
            },
        )

        self.assertIn("mentionnee dans 3 comptes rendus", candidates[0]["detail"])

    def test_detects_later_task_lookup_without_confusing_decision(self) -> None:
        self.assertTrue(is_offer_later_task_lookup_request("Quelles taches restent a plus tard ?"))
        self.assertTrue(is_offer_later_task_lookup_request("liste les tâches plus tard pour Guillaume"))
        self.assertFalse(is_offer_later_task_lookup_request("dans l'offre T1, plus tard T2, oublier T3"))


if __name__ == "__main__":
    unittest.main()
