from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from server.app.db import db
from server.app.main import app
from server.app.offer_service import ensure_offer_schema


ORIGIN = "http://localhost:5173"
REPORT_TASK_TITLES = [
    "Valider le cahier des charges final",
    "Preparer les contenus de la page d'accueil",
    "Envoyer les acces de preproduction",
]
LATER_TASK_TITLE = REPORT_TASK_TITLES[1]
FORGOTTEN_TASK_TITLE = REPORT_TASK_TITLES[2]
INCLUDED_TASK_TITLE = REPORT_TASK_TITLES[0]


async def prepare_database_case() -> dict[str, str]:
    await db.connect()
    try:
        await ensure_offer_schema()
        async with db.acquire() as connection:
            client = await connection.fetchrow(
                """
                SELECT clients.id::text, clients.site_id::text, clients.name
                FROM clients
                JOIN client_artifacts ON client_artifacts.client_id = clients.id
                JOIN client_project_tasks ON client_project_tasks.client_id = clients.id
                GROUP BY clients.id, clients.site_id, clients.name
                HAVING count(DISTINCT client_artifacts.id) > 0
                   AND count(DISTINCT client_project_tasks.id) > 0
                ORDER BY clients.updated_at DESC, clients.name ASC
                LIMIT 1
                """
            )
            if client is None:
                raise RuntimeError("No existing client with artifacts and tasks was found in the database.")

            primary_project = await upsert_client_project(
                connection,
                client["id"],
                "E2E Offre - Portail Client",
                "Projet de test rattache a un client reel pour valider le flux offre complet.",
            )
            await upsert_client_project(
                connection,
                client["id"],
                "E2E Offre - Application Mobile",
                "Second projet de test pour verifier que l'agent demande lequel choisir.",
            )
            artifact = await upsert_report_artifact(connection, client["id"], primary_project["id"])
            for title in REPORT_TASK_TITLES:
                await upsert_project_task(connection, client["id"], primary_project["id"], artifact["id"], title)

        return {
            "site_id": client["site_id"],
            "client_name": client["name"],
            "project_name": primary_project["name"],
        }
    finally:
        await db.close()


async def upsert_client_project(connection: Any, client_id: str, name: str, summary: str) -> dict[str, str]:
    row = await connection.fetchrow(
        """
        SELECT id::text, name
        FROM client_projects
        WHERE client_id = $1::uuid AND name = $2
        """,
        client_id,
        name,
    )
    if row:
        return dict(row)
    created = await connection.fetchrow(
        """
        INSERT INTO client_projects(client_id, name, status, summary, updated_at)
        VALUES($1::uuid, $2, 'en cours', $3, now())
        RETURNING id::text, name
        """,
        client_id,
        name,
        summary,
    )
    return dict(created)


async def upsert_report_artifact(connection: Any, client_id: str, project_id: str) -> dict[str, str]:
    title = "E2E Compte rendu avec actions offre"
    row = await connection.fetchrow(
        """
        SELECT id::text
        FROM client_artifacts
        WHERE client_id = $1::uuid AND project_id = $2::uuid AND title = $3
        """,
        client_id,
        project_id,
        title,
    )
    if row:
        return dict(row)
    content = "\n".join(
        [
            "Compte rendu Noota - Atelier cadrage offre",
            "",
            "Synthese",
            "Le client veut cadrer une proposition commerciale pour son portail client.",
            "",
            "Actions",
            f"- {INCLUDED_TASK_TITLE} | Responsable: Alice | Echeance: 2026-08-01",
            f"- {LATER_TASK_TITLE} | Responsable: Bruno | Echeance: 2026-08-08",
            f"- {FORGOTTEN_TASK_TITLE} | Responsable: Claire | Echeance: 2026-08-15",
        ]
    )
    created = await connection.fetchrow(
        """
        INSERT INTO client_artifacts(client_id, project_id, title, kind, content, updated_at)
        VALUES($1::uuid, $2::uuid, $3, 'noota_report', $4, now())
        RETURNING id::text
        """,
        client_id,
        project_id,
        title,
        content,
    )
    return dict(created)


async def upsert_project_task(connection: Any, client_id: str, project_id: str, artifact_id: str, title: str) -> None:
    existing = await connection.fetchval(
        """
        SELECT 1
        FROM client_project_tasks
        WHERE client_id = $1::uuid
          AND project_id = $2::uuid
          AND title = $3
        """,
        client_id,
        project_id,
        title,
    )
    if existing:
        return
    await connection.execute(
        """
        INSERT INTO client_project_tasks(client_id, project_id, artifact_id, title, owner, due_date, status, source_excerpt, updated_at)
        VALUES($1::uuid, $2::uuid, $3::uuid, $4, 'Equipe projet', '2026-08-01', 'proposed', $5, now())
        """,
        client_id,
        project_id,
        artifact_id,
        title,
        f"Action issue du compte rendu: {title}",
    )


def run_offer_flow(case: dict[str, str]) -> dict[str, Any]:
    with TestClient(app) as client:
        create_response = client.post(
            "/offers/projects",
            json={"site_id": case["site_id"], "title": "E2E Offre - test utilisateur"},
            headers={"Origin": ORIGIN},
        )
        assert_ok(create_response, "create offer project")
        offer_project = create_response.json()
        offer_project_id = offer_project["id"]

        first_message = client.post(
            f"/offers/projects/{offer_project_id}/messages",
            params={"site_id": case["site_id"]},
            json={"content": f"On va bosser sur le projet de {case['client_name']}"},
            headers={"Origin": ORIGIN},
        )
        assert_ok(first_message, "first offer message")
        first_answer = first_message.json()["message"]["content"]

        project_choice = client.post(
            f"/offers/projects/{offer_project_id}/messages",
            params={"site_id": case["site_id"]},
            json={"content": case["project_name"]},
            headers={"Origin": ORIGIN},
        )
        assert_ok(project_choice, "project choice")
        project_choice_answer = project_choice.json()["message"]["content"]

        decision_message = (
            "dans l'offre T1, plus tard T2, oublier T3"
        )
        decision = client.post(
            f"/offers/projects/{offer_project_id}/messages",
            params={"site_id": case["site_id"]},
            json={"content": decision_message},
            headers={"Origin": ORIGIN},
        )
        assert_ok(decision, "task decision")
        decision_answer = decision.json()["message"]["content"]

        later_lookup = client.post(
            "/chat",
            json={
                "site_id": case["site_id"],
                "message": f"Quelles taches restent a plus tard pour {case['client_name']} ?",
                "history": [],
            },
            headers={"Origin": ORIGIN},
        )
        assert_ok(later_lookup, "general chat later task lookup")
        later_lookup_answer = later_lookup.json()["answer"]

        generated = client.post(
            f"/offers/projects/{offer_project_id}/generate",
            params={"site_id": case["site_id"]},
            headers={"Origin": ORIGIN},
        )
        assert_ok(generated, "generate offer")
        generated_context = generated.json()

        return {
            "case": case,
            "offer_project_id": offer_project_id,
            "first_answer": first_answer,
            "project_choice_answer": project_choice_answer,
            "decision_message": decision_message,
            "decision_answer": decision_answer,
            "later_lookup_answer": later_lookup_answer,
            "generated_offer_markdown": generated_context["generated_offer_markdown"],
            "linked_client": generated_context.get("linked_client"),
            "linked_client_project": generated_context.get("linked_client_project"),
            "client_project_tasks": generated_context.get("client_project_tasks", []),
        }


def assert_ok(response: Any, label: str) -> None:
    if 200 <= response.status_code < 300:
        return
    raise AssertionError(f"{label} failed with {response.status_code}: {response.text}")


def deterministic_assertions(result: dict[str, Any]) -> dict[str, Any]:
    task_titles = extract_displayed_task_titles(result["project_choice_answer"])
    included_title = task_titles.get("T1", "")
    later_title = task_titles.get("T2", "")
    forgotten_title = task_titles.get("T3", "")
    selected_section = selected_tasks_section(result["generated_offer_markdown"])
    checks = {
        "asks_project_when_multiple": "Lequel doit servir de contexte" in result["first_answer"],
        "loads_context_after_choice": "Contexte charge" in result["project_choice_answer"],
        "shows_task_classification": "Voici les taches a classer" in result["project_choice_answer"],
        "uses_report_task_included": bool(included_title) and included_title in result["project_choice_answer"],
        "persists_include_decision": "dans l'offre : T1" in result["decision_answer"],
        "general_chat_lists_later_task": bool(later_title) and later_title in result["later_lookup_answer"],
        "general_chat_excludes_included_task_from_later": bool(included_title) and included_title not in result["later_lookup_answer"],
        "generated_contains_included_task": bool(included_title) and included_title in selected_section,
        "generated_excludes_later_task_from_selected_section": bool(later_title) and later_title not in selected_section,
        "generated_excludes_forgotten_task_from_selected_section": bool(forgotten_title) and forgotten_title not in selected_section,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "task_mapping": {
            "T1": included_title,
            "T2": later_title,
            "T3": forgotten_title,
        },
    }


def extract_displayed_task_titles(answer: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for match in re.finditer(r"- (T\d+) - ([^\n:]+)", answer):
        mapping[match.group(1)] = match.group(2).strip()
    return mapping


def selected_tasks_section(markdown: str) -> str:
    marker = "### Taches retenues dans l'offre"
    start = markdown.find(marker)
    if start < 0:
        return ""
    rest = markdown[start + len(marker):]
    next_section = rest.find("\n## ")
    return rest if next_section < 0 else rest[:next_section]


def run_llm_judge(result: dict[str, Any], deterministic: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"skipped": True, "reason": "OPENAI_API_KEY is not configured."}

    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    prompt = {
        "scenario": "Evaluation end-to-end du flux proposition d'offre.",
        "expected_behavior": [
            "L'agent doit reconnaitre le client et demander le projet si plusieurs projets existent.",
            "Apres choix du projet, il doit charger le contexte du projet: comptes rendus, reunions, taches.",
            "La liste des taches a classer doit provenir des rapports/projets client, pas de taches internes de production d'offre.",
            "Le choix utilisateur doit classer les taches en dans l'offre, plus tard, oublie.",
            "Une question generale comme 'quelles taches restent a plus tard ?' doit lister les taches classees plus tard.",
            "Le brouillon doit mettre dans la section des taches retenues uniquement les taches choisies dans l'offre.",
        ],
        "deterministic_checks": deterministic,
        "conversation_and_output": result,
    }
    response = client.chat.completions.create(
        model=os.getenv("OFFER_E2E_JUDGE_MODEL", os.getenv("CHATBOT_JUDGE_MODEL", "gpt-4.1-mini")),
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un juge QA pour une application de proposition d'offre. "
                    "Reponds uniquement en JSON valide avec les cles overall (1-5), passed (bool), "
                    "strengths (liste), weaknesses (liste), summary (string)."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content or ""
    return json.loads(extract_json_object(content))


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object found in judge output: {text!r}")
    return text[start : end + 1]


def main() -> None:
    case = asyncio.run(prepare_database_case())
    result = run_offer_flow(case)
    deterministic = deterministic_assertions(result)
    judge = run_llm_judge(result, deterministic)
    report = {
        "case": case,
        "deterministic": deterministic,
        "judge": judge,
        "result_excerpt": {
            "first_answer": result["first_answer"],
            "project_choice_answer": result["project_choice_answer"],
            "decision_answer": result["decision_answer"],
            "later_lookup_answer": result["later_lookup_answer"],
            "selected_tasks_section": selected_tasks_section(result["generated_offer_markdown"]),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not deterministic["passed"]:
        raise SystemExit(1)
    if not judge.get("skipped") and not judge.get("passed", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
