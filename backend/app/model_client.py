# =============================================================================
# model_client.py
# Purpose : Calls the project's AI server (/extract and /explain).
# Privacy : Images and patient results stay in memory and are never logged.
# =============================================================================
import base64
import logging
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import settings
from .safety import find_urgent_terms, parse_number, status_from_range
from .schemas import LlmLab, LlmOutput, LlmRadiology

log = logging.getLogger("tahlili.model")


class ModelError(Exception):
    """Raised when the model is unreachable or returns unusable output."""


def _ai_base_url() -> str:
    """Normalize either a server root or an OpenAI-style `/v1` URL."""
    parts = urlsplit(settings.llm_api_url.rstrip("/"))
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment)).rstrip("/")


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    header, encoded = data_url.split(",", 1)
    mime = header.removeprefix("data:").removesuffix(";base64")
    return mime, base64.b64decode(encoded, validate=True)


async def _extract(client: httpx.AsyncClient, data_url: str, label: str) -> dict:
    mime, data = _decode_data_url(data_url)
    response = await client.post(
        f"{_ai_base_url()}/extract",
        headers={"X-API-KEY": settings.llm_api_key} if settings.llm_api_key else {},
        files={"file": (f"{label}.img", data, mime)},
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("invalid extraction response")
    return result


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _severity(value_text: str, low: float | None, high: float | None) -> str:
    status = status_from_range(value_text, low, high)
    if status == "green":
        return "normal"
    value = parse_number(value_text)
    if status is None or value is None:
        return "unknown"
    return "low" if low is not None and value < low else "high"


async def _explain(
    client: httpx.AsyncClient,
    labs: list[LlmLab],
    radiology: list[LlmRadiology],
) -> dict:
    results = []
    for lab in labs:
        results.append({
            "name": lab.name,
            "value": lab.value,
            "unit": lab.unit,
            "status": _severity(lab.value, lab.ref_low, lab.ref_high),
            "ref_low": lab.ref_low,
            "ref_high": lab.ref_high,
        })

    combined_text = " ".join(
        part for rad in radiology for part in (rad.original_text, rad.findings) if part
    )
    urgent_flags = find_urgent_terms(combined_text)
    specialties = [
        ("باطنة أو غدد", ("hba1c", "سكر", "tsh", "thyroid", "غدة")),
        ("باطنة أو كلى", ("creatinine", "urea", "كرياتينين", "يوريا")),
        ("باطنة أو كبد", ("alt", "ast", "bilirubin", "كبد")),
        ("باطنة أو أمراض دم", ("hemoglobin", "hb", "ferritin", "cbc", "هيموجلوبين", "فيريتين")),
    ]
    names = " ".join(lab.name.lower() for lab in labs)
    doctor_type = next((doctor for doctor, terms in specialties if any(term in names for term in terms)), None)
    if doctor_type is None and labs:
        doctor_type = "باطنة"

    rad_input = None
    if radiology:
        rad_input = {
            "modality": ", ".join(dict.fromkeys(rad.type for rad in radiology if rad.type)),
            "findings": [rad.findings for rad in radiology if rad.findings],
            "impression": " ".join(rad.original_text for rad in radiology if rad.original_text),
            "severity": "urgent" if urgent_flags else "unknown",
        }

    request_body = {
        "report_type": "both" if labs and radiology else ("radiology" if radiology else "lab"),
        "results": results,
        "radiology": rad_input,
        "doctor_type": doctor_type,
        "urgent_flags": urgent_flags,
    }
    response = await client.post(
        f"{_ai_base_url()}/explain",
        headers={"X-API-KEY": settings.llm_api_key} if settings.llm_api_key else {},
        json=request_body,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("invalid explanation response")
    result["_doctor_type"] = doctor_type
    return result


async def analyze_images(lab_urls: list[str], rad_urls: list[str]) -> LlmOutput:
    """Extract report data, classify it locally, then request Arabic explanations."""
    try:
        timeout = httpx.Timeout(settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            lab_data = [await _extract(client, image, f"lab-{i}") for i, image in enumerate(lab_urls, 1)]
            rad_data = [await _extract(client, image, f"radiology-{i}") for i, image in enumerate(rad_urls, 1)]

            labs: list[LlmLab] = []
            for data in lab_data:
                for item in _as_list(data.get("tests")):
                    test = _as_dict(item)
                    value = test.get("value")
                    value_text = test.get("value_text")
                    labs.append(LlmLab(
                        name=test.get("name") or "",
                        value=str(value if value is not None else value_text or ""),
                        unit=test.get("unit") or "",
                        ref_low=test.get("ref_low"),
                        ref_high=test.get("ref_high"),
                    ))

            radiology: list[LlmRadiology] = []
            for data in rad_data:
                item = _as_dict(data.get("radiology"))
                if not item:
                    continue
                findings = " ".join(str(value) for value in _as_list(item.get("findings")) if value)
                original = " ".join(str(value) for value in (findings, item.get("impression")) if value)
                label = " ".join(str(value) for value in (item.get("modality"), item.get("body_part")) if value)
                radiology.append(LlmRadiology(type=label or "تقرير أشعة", findings=findings, original_text=original))

            if not labs and not radiology:
                return LlmOutput()

            explanation = await _explain(client, labs, radiology)
        explanation_by_name = {
            str(item.get("name", "")): str(item.get("text", ""))
            for item in _as_list(explanation.get("explanations"))
            if isinstance(item, dict)
        }
        for lab in labs:
            lab.explanation = explanation_by_name.get(lab.name, "")

        summaries = [str(line) for line in _as_list(explanation.get("summary")) if line]
        summary = " ".join(summaries)
        pattern = explanation.get("pattern")
        if pattern:
            summary = f"{summary} {pattern}".strip()
        priority = explanation.get("priority")
        status = "red" if priority == "see_doctor_soon" else "yellow" if priority == "follow_up" else "green"
        for lab in labs:
            by_range = status_from_range(lab.value, lab.ref_low, lab.ref_high)
            lab.status = by_range or "yellow"
        for rad in radiology:
            rad.status = "red" if find_urgent_terms(rad.original_text) else status
            rad.explanation = pattern or (summaries[1] if len(summaries) > 1 else summary)

        return LlmOutput(
            summary=summary,
            labs=labs,
            radiology=radiology,
            doctor=explanation.get("_doctor_type") or "",
            questions=_as_list(explanation.get("doctor_questions")),
        )
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        # Log only the error type: never log patient content or credentials.
        log.warning("model call failed: %s", type(exc).__name__)
        raise ModelError("model call failed") from exc
