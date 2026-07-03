from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

from dotenv import dotenv_values, load_dotenv
from openai import OpenAI

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.chatbot_fidelity_suite import CASES as EVAL_CASES
from tests.chatbot_fidelity_suite import DEFAULT_API_URL, DEFAULT_SITE_ID, _normalize


DEFAULT_JUDGE_MODEL = os.getenv("CHATBOT_JUDGE_MODEL", "gpt-4.1-mini")
ENV_VALUES = dotenv_values(".env")
DEFAULT_REPORT_PATH = os.getenv("CHATBOT_EVAL_REPORT_PATH", "reports/latest_eval.json")
DEFAULT_ROUTER_MODEL = os.getenv("OPENAI_ROUTER_MODEL", ENV_VALUES.get("OPENAI_ROUTER_MODEL", "gpt-4.1-mini"))
DEFAULT_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", ENV_VALUES.get("OPENAI_CHAT_MODEL", "moonshotai/kimi-k2.5"))
ROUTER_INPUT_COST_PER_M = float(os.getenv("ROUTER_INPUT_COST_PER_M", "0.40"))
ROUTER_OUTPUT_COST_PER_M = float(os.getenv("ROUTER_OUTPUT_COST_PER_M", "1.60"))
JUDGE_INPUT_COST_PER_M = float(os.getenv("JUDGE_INPUT_COST_PER_M", str(ROUTER_INPUT_COST_PER_M)))
JUDGE_OUTPUT_COST_PER_M = float(os.getenv("JUDGE_OUTPUT_COST_PER_M", str(ROUTER_OUTPUT_COST_PER_M)))
CHAT_INPUT_COST_PER_M = float(os.getenv("CHAT_INPUT_COST_PER_M", "0.0"))
CHAT_OUTPUT_COST_PER_M = float(os.getenv("CHAT_OUTPUT_COST_PER_M", "0.0"))


def call_chat(payload: dict[str, Any]) -> tuple[int, dict[str, Any] | str]:
    req = request.Request(
        f"{DEFAULT_API_URL}/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": "http://localhost:5173",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed
    except error.URLError as exc:
        raise RuntimeError(
            "Unable to reach the chatbot API. "
            f"Start the server on {DEFAULT_API_URL} or override CHATBOT_TEST_API_URL. Details: {exc}"
        ) from exc


def evaluate_fidelity() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed = 0
    usage_totals = empty_usage_totals()

    for case in EVAL_CASES:
        status, body = call_chat({"site_id": DEFAULT_SITE_ID, "message": case.question, "history": []})
        ok = True
        reasons: list[str] = []

        if status != 200 or not isinstance(body, dict):
            ok = False
            reasons.append(f"unexpected_status={status}")
            answer = ""
            source_urls: list[str] = []
            usage = None
        else:
            answer = str(body.get("answer", ""))
            sources = body.get("sources", [])
            usage = body.get("usage", {})
            source_urls = [item.get("url", "") for item in sources if isinstance(item, dict)] if isinstance(sources, list) else []
            normalized_answer = _normalize(answer)
            add_usage(usage_totals, usage)

            if not answer.strip():
                ok = False
                reasons.append("empty_answer")

            if case.expected_answer is not None and answer != case.expected_answer:
                ok = False
                reasons.append(f"unexpected_answer:{case.expected_answer!r}")

            for keyword in case.expected_keywords:
                if _normalize(keyword) not in normalized_answer:
                    ok = False
                    reasons.append(f"missing_keyword:{keyword}")

            for keyword in case.forbidden_keywords:
                if _normalize(keyword) in normalized_answer:
                    ok = False
                    reasons.append(f"forbidden_keyword:{keyword}")

            if case.expected_source_url is not None and case.expected_source_url not in source_urls:
                ok = False
                reasons.append(f"missing_source:{case.expected_source_url}")

        if ok:
            passed += 1

        results.append(
            {
                "case": case.name,
                "question": case.question,
                "passed": ok,
                "reasons": reasons,
                "answer": answer,
                "source_urls": source_urls,
                "usage": usage,
                "response": body if status == 200 and isinstance(body, dict) else None,
            }
        )

    note = round((passed / len(EVAL_CASES)) * 5, 2)
    return {
        "note_on_5": note,
        "passed_cases": passed,
        "total_cases": len(EVAL_CASES),
        "usage_totals": usage_totals,
        "details": results,
    }


def evaluate_pertinence(fidelity_details: list[dict[str, Any]]) -> dict[str, Any]:
    return evaluate_judged_dimension(
        fidelity_details=fidelity_details,
        dimension_name="pertinence",
        system_prompt=(
            "Tu es un evaluateur de pertinence pour un chatbot de site web en francais. "
            "Tu juges si les reponses repondent vraiment a la question posee, restent dans le bon perimetre, "
            "et donnent un niveau de detail utile sans partir hors sujet. "
            "Tu ne notes pas la veracite factuelle fine, seulement la pertinence de la reponse par rapport a la question. "
            "Donne une note globale entiere de 1 a 5. "
            "5 = tres pertinent, 4 = pertinent, 3 = partiellement pertinent, 2 = peu pertinent, 1 = hors sujet. "
            "Reponds uniquement en JSON valide avec les cles overall, strengths, weaknesses, summary."
        ),
    )


def evaluate_coherence(fidelity_details: list[dict[str, Any]]) -> dict[str, Any]:
    return evaluate_judged_dimension(
        fidelity_details=fidelity_details,
        dimension_name="coherence",
        system_prompt=(
            "Tu es un evaluateur de coherence redactionnelle pour un chatbot de site web en francais. "
            "Tu juges la clarte interne des reponses, leur logique, leur fluidite, l'absence de contradictions "
            "et la facilite de lecture sur l'ensemble du corpus. "
            "Tu ne notes pas la veracite metier. "
            "Donne une note globale entiere de 1 a 5. "
            "5 = tres coherent, 4 = coherent, 3 = globalement coherent mais inegal, 2 = confus, 1 = incoherent. "
            "Reponds uniquement en JSON valide avec les cles overall, strengths, weaknesses, summary."
        ),
    )


def evaluate_judged_dimension(
    fidelity_details: list[dict[str, Any]],
    dimension_name: str,
    system_prompt: str,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"OPENAI_API_KEY is required for the {dimension_name} evaluation.")

    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    exchanges: list[dict[str, str]] = []
    for item in fidelity_details:
        response = item.get("response")
        if not isinstance(response, dict):
            raise RuntimeError(f"{dimension_name} evaluation cannot reuse fidelity response for case={item.get('case')}.")
        exchanges.append({"question": str(item.get("question", "")), "answer": str(response.get("answer", ""))})

    user_prompt = (
        f"J'ai pose {len(exchanges)} questions a un chatbot. "
        f"Evalue uniquement la {dimension_name} globale des reponses.\n\n"
        + "\n\n".join(
            f"{index}. Question: {item['question']}\nReponse: {item['answer']}"
            for index, item in enumerate(exchanges, start=1)
        )
    )

    response = client.chat.completions.create(
        model=DEFAULT_JUDGE_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or ""
    payload = json.loads(extract_json_object(content))
    judge_usage = usage_to_dict(response.usage)
    return {
        "note_on_5": float(payload["overall"]),
        "questions_evaluated": len(exchanges),
        "strengths": payload.get("strengths", []),
        "weaknesses": payload.get("weaknesses", []),
        "summary": payload.get("summary", ""),
        "judge_usage": judge_usage,
    }


def extract_json_object(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in judge output: {text!r}")
    return cleaned[start : end + 1]


def usage_to_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def empty_usage_totals() -> dict[str, dict[str, int]]:
    return {
        "route": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "rewrite": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "answer": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def add_usage(accumulator: dict[str, dict[str, int]], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    for stage in ["route", "rewrite", "answer", "total"]:
        stage_usage = usage.get(stage)
        if not isinstance(stage_usage, dict):
            continue
        for key in ["prompt_tokens", "completion_tokens", "total_tokens"]:
            accumulator[stage][key] += int(stage_usage.get(key, 0) or 0)


def sum_usage_blocks(*blocks: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    total = empty_usage_totals()
    for block in blocks:
        add_usage(total, block)
    return total


def sum_flat_usages(*usages: dict[str, int]) -> dict[str, int]:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for usage in usages:
        for key in total:
            total[key] += int(usage.get(key, 0) or 0)
    return total


def compute_cost_usd(usage: dict[str, int], input_cost_per_m: float, output_cost_per_m: float) -> float:
    return round(
        (usage.get("prompt_tokens", 0) / 1_000_000) * input_cost_per_m
        + (usage.get("completion_tokens", 0) / 1_000_000) * output_cost_per_m,
        6,
    )


def main() -> int:
    try:
        fidelity = evaluate_fidelity()
        pertinence = evaluate_pertinence(fidelity["details"])
        coherence = evaluate_coherence(fidelity["details"])
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    all_judge_usage = sum_flat_usages(pertinence["judge_usage"], coherence["judge_usage"])

    summary = {
        "api_url": DEFAULT_API_URL,
        "site_id": DEFAULT_SITE_ID,
        "questions_evaluated": len(EVAL_CASES),
        "models": {
            "router": DEFAULT_ROUTER_MODEL,
            "chat": DEFAULT_CHAT_MODEL,
            "judge": DEFAULT_JUDGE_MODEL,
        },
        "notes_on_5": {
            "pertinence": pertinence["note_on_5"],
            "fidelity": fidelity["note_on_5"],
            "coherence": coherence["note_on_5"],
        },
        "token_usage": {
            "chatbot_calls": fidelity["usage_totals"],
            "judge_pertinence": pertinence["judge_usage"],
            "judge_coherence": coherence["judge_usage"],
            "judge_total": all_judge_usage,
            "grand_total": {
                "chat": fidelity["usage_totals"],
                "judge": all_judge_usage,
                "combined": sum_flat_usages(fidelity["usage_totals"]["total"], all_judge_usage),
            },
        },
        "cost_usd": {
            "pricing": {
                "router_model": {
                    "model": DEFAULT_ROUTER_MODEL,
                    "input_cost_per_m": ROUTER_INPUT_COST_PER_M,
                    "output_cost_per_m": ROUTER_OUTPUT_COST_PER_M,
                },
                "chat_model": {
                    "model": DEFAULT_CHAT_MODEL,
                    "input_cost_per_m": CHAT_INPUT_COST_PER_M,
                    "output_cost_per_m": CHAT_OUTPUT_COST_PER_M,
                },
                "judge_model": {
                    "model": DEFAULT_JUDGE_MODEL,
                    "input_cost_per_m": JUDGE_INPUT_COST_PER_M,
                    "output_cost_per_m": JUDGE_OUTPUT_COST_PER_M,
                },
            },
            "chatbot": {
                "router_rewrite": compute_cost_usd(
                    sum_flat_usages(
                        fidelity["usage_totals"]["route"],
                        fidelity["usage_totals"]["rewrite"],
                    ),
                    ROUTER_INPUT_COST_PER_M,
                    ROUTER_OUTPUT_COST_PER_M,
                ),
                "answer": compute_cost_usd(
                    fidelity["usage_totals"]["answer"],
                    CHAT_INPUT_COST_PER_M,
                    CHAT_OUTPUT_COST_PER_M,
                ),
                "total": round(
                    compute_cost_usd(
                        sum_flat_usages(
                            fidelity["usage_totals"]["route"],
                            fidelity["usage_totals"]["rewrite"],
                        ),
                        ROUTER_INPUT_COST_PER_M,
                        ROUTER_OUTPUT_COST_PER_M,
                    )
                    + compute_cost_usd(
                        fidelity["usage_totals"]["answer"],
                        CHAT_INPUT_COST_PER_M,
                        CHAT_OUTPUT_COST_PER_M,
                    ),
                    6,
                ),
            },
            "judges": {
                "pertinence": compute_cost_usd(
                    pertinence["judge_usage"],
                    JUDGE_INPUT_COST_PER_M,
                    JUDGE_OUTPUT_COST_PER_M,
                ),
                "coherence": compute_cost_usd(
                    coherence["judge_usage"],
                    JUDGE_INPUT_COST_PER_M,
                    JUDGE_OUTPUT_COST_PER_M,
                ),
                "total": compute_cost_usd(
                    all_judge_usage,
                    JUDGE_INPUT_COST_PER_M,
                    JUDGE_OUTPUT_COST_PER_M,
                ),
            },
            "grand_total": round(
                compute_cost_usd(
                    sum_flat_usages(
                        fidelity["usage_totals"]["route"],
                        fidelity["usage_totals"]["rewrite"],
                    ),
                    ROUTER_INPUT_COST_PER_M,
                    ROUTER_OUTPUT_COST_PER_M,
                )
                + compute_cost_usd(
                    fidelity["usage_totals"]["answer"],
                    CHAT_INPUT_COST_PER_M,
                    CHAT_OUTPUT_COST_PER_M,
                )
                + compute_cost_usd(
                    all_judge_usage,
                    JUDGE_INPUT_COST_PER_M,
                    JUDGE_OUTPUT_COST_PER_M,
                ),
                6,
            ),
        },
        "pertinence": pertinence,
        "fidelity": fidelity,
        "coherence": coherence,
    }

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    report_path = ROOT_DIR / DEFAULT_REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
