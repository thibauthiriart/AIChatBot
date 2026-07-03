from __future__ import annotations

import json
import os
import unittest
from typing import Any
from urllib import error, request

from openai import OpenAI

from tests.chatbot_fidelity_suite import CASES, DEFAULT_API_URL, DEFAULT_SITE_ID


DEFAULT_JUDGE_MODEL = os.getenv("CHATBOT_JUDGE_MODEL", "gpt-4.1-mini")


class ChatbotPertinenceTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise unittest.SkipTest("OPENAI_API_KEY is required for pertinence evaluation.")

        cls.judge_client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )

    def test_pertinence_cases(self) -> None:
        self.assertEqual(len(CASES), 20, "The evaluation corpus must stay at 20 questions.")
        exchanges: list[dict[str, str]] = []

        for case in CASES:
            with self.subTest(case=case.name):
                chatbot_response = self._call_chat(case.question)
                answer = chatbot_response.get("answer", "")
                self.assertTrue(answer.strip(), "The chatbot answer must not be empty before pertinence evaluation.")
                exchanges.append({"question": case.question, "answer": answer})

        evaluation = self._judge_pertinence(exchanges)
        print(json.dumps(evaluation, ensure_ascii=False, indent=2))

    def _call_chat(self, question: str) -> dict[str, Any]:
        payload = json.dumps(
            {
                "site_id": DEFAULT_SITE_ID,
                "message": question,
                "history": [],
            }
        ).encode("utf-8")
        req = request.Request(
            f"{DEFAULT_API_URL}/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": "http://localhost:5173",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.fail(f"/chat returned HTTP {exc.code} for question {question!r}: {body}")
        except error.URLError as exc:
            self.fail(
                "Unable to reach the chatbot API. "
                f"Start the server on {DEFAULT_API_URL} or override CHATBOT_TEST_API_URL. Details: {exc}"
            )

    def _judge_pertinence(self, exchanges: list[dict[str, str]]) -> dict[str, Any]:
        system_prompt = (
            "Tu es un evaluateur de pertinence pour un chatbot de site web en francais. "
            "Tu juges si les reponses repondent vraiment aux questions posees, restent dans le perimetre attendu, "
            "et donnent une aide utile sans partir hors sujet. "
            "Tu ne notes pas la veracite factuelle fine. "
            "Donne une note globale entiere de 1 a 5. "
            "Reponds uniquement en JSON valide avec les cles overall, strengths, weaknesses, summary."
        )
        user_prompt = (
            f"J'ai pose {len(exchanges)} questions a un chatbot. "
            "Evalue uniquement la pertinence globale des reponses.\n\n"
            + "\n\n".join(
                f"{index}. Question: {item['question']}\nReponse: {item['answer']}"
                for index, item in enumerate(exchanges, start=1)
            )
        )

        response = self.judge_client.chat.completions.create(
            model=DEFAULT_JUDGE_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        try:
            return json.loads(self._extract_json_object(content))
        except Exception as exc:
            self.fail(f"Pertinence judge did not return valid JSON. Raw content: {content!r}. Error: {exc}")

    def _extract_json_object(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found")
        return cleaned[start : end + 1]


if __name__ == "__main__":
    unittest.main()
