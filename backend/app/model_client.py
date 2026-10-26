# =============================================================================
# model_client.py
# Purpose : The ONLY file that talks to the model API.
# Logic   : Sends the images + system prompt to an OpenAI-compatible
#           /chat/completions endpoint (Ollama, vLLM, LM Studio, hosted APIs),
#           extracts the JSON from the answer and validates it.
#           If your model has a different API, change only _call_api().
#           With MOCK_LLM=true it returns demo data and calls nothing.
# =============================================================================
import json
import logging

import httpx

from .config import settings
from .prompts import SYSTEM_PROMPT
from .schemas import LlmOutput

log = logging.getLogger("tahlili.model")


class ModelError(Exception):
    """Raised when the model is unreachable or returns unusable output."""


# Demo answer in the SAME shape the real model must return (used when MOCK_LLM=true)
MOCK_OUTPUT = {
    "summary": "أغلب نتايجك كويسة، بس عندك نقص بسيط في الحديد وسكر تراكمي عالي. كلم دكتورك قريب.",
    "labs": [
        {"name": "فيتامين د (Vitamin D)", "value": "50", "unit": "ng/mL", "ref_low": 30, "ref_high": 100,
         "status": "green", "explanation": "ده بيقيس مخزون فيتامين د في جسمك، ورقمك كويس."},
        {"name": "الهيموجلوبين (Hb)", "value": "10.2", "unit": "g/dL", "ref_low": 12, "ref_high": 15.5,
         "status": "yellow", "explanation": "ده بيقيس كمية الدم اللي شايلة الأكسجين. رقمك أقل شوية من الطبيعي."},
        {"name": "السكر التراكمي (HbA1c)", "value": "8.4", "unit": "%", "ref_low": 4, "ref_high": 5.7,
         "status": "yellow", "explanation": "ده متوسط السكر في الدم آخر 3 شهور. رقمك عالي عن الطبيعي."},
    ],
    "radiology": [
        {"type": "سونار على البطن", "findings": "دهون بسيطة على الكبد (درجة أولى).",
         "original_text": "Mild fatty liver (grade I). No focal mass lesion. No free fluid.",
         "status": "yellow", "explanation": "معناها إن فيه دهون قليلة على الكبد، وغالبا بتتحسن بالأكل والحركة."},
    ],
    "doctor": "باطنة أو غدد",
    "questions": [
        "هل الهيموجلوبين الواطي سببه نقص حديد؟",
        "محتاج أعمل تحليل متابعة إمتى؟",
        "السكر التراكمي العالي محتاج إيه بعد كده؟",
    ],
}


def _build_messages(lab_urls: list[str], rad_urls: list[str]) -> list[dict]:
    """Build the chat messages: system prompt + labeled images."""
    content: list[dict] = [{"type": "text", "text": "Read the following photos and return the JSON only."}]
    for i, url in enumerate(lab_urls, 1):
        content.append({"type": "text", "text": f"Lab result sheet {i}:"})
        content.append({"type": "image_url", "image_url": {"url": url}})
    for i, url in enumerate(rad_urls, 1):
        content.append({"type": "text", "text": f"Radiology report {i}:"})
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's text (ignores code fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model answer")
    return json.loads(text[start:end + 1])


async def _call_api(messages: list[dict]) -> str:
    """POST to the model API and return the answer text. Change this for a custom API."""
    payload: dict = {"model": settings.llm_model, "messages": messages, "temperature": 0, "stream": False}
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    url = f"{settings.llm_api_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


async def analyze_images(lab_urls: list[str], rad_urls: list[str]) -> LlmOutput:
    """Send the images to the model and return its validated answer."""
    if settings.mock_llm:
        return LlmOutput.model_validate(MOCK_OUTPUT)
    try:
        text = await _call_api(_build_messages(lab_urls, rad_urls))
        return LlmOutput.model_validate(_extract_json(text))
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        # Log only the error type: never log patient content.
        log.warning("model call failed: %s", type(exc).__name__)
        raise ModelError("model call failed") from exc
