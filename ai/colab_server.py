"""
Tahlili AI server (runs on Colab).
Only does AI: /extract (image -> JSON) and /explain (statuses -> Arabic explanation).
All judging logic (normal/high/low, urgent flags) lives in the backend, NOT here.
"""
import base64
import io
import json
import os
import re
import time
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel

OLLAMA = "http://localhost:11434"
MODEL = os.getenv("MODEL", "gemma4:e4b")
API_KEY = os.getenv("API_KEY", "dev-key")
PROMPTS = Path(__file__).parent / "prompts"
MAX_SIDE = 1600  # resize big phone photos: faster, usually same accuracy

app = FastAPI(title="Tahlili AI")


def check_key(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="bad api key")


def read_prompt(name: str) -> str:
    # read on every call so you can edit prompts without restarting the server
    return (PROMPTS / name).read_text(encoding="utf-8")


def parse_json(text: str) -> dict:
    """Be forgiving: strip code fences, grab the outermost {...}."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def call_gemma(system: str, user_text: str, image_b64: str | None = None) -> str:
    user_msg = {"role": "user", "content": user_text}
    if image_b64:
        user_msg["images"] = [image_b64]
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, user_msg],
        "stream": False,
        "format": "json",
        "keep_alive": "60m",
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }
    r = requests.post(f"{OLLAMA}/api/chat", json=payload, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


def prep_image(raw: bytes) -> str:
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/health")
def health():
    try:
        tags = requests.get(f"{OLLAMA}/api/tags", timeout=5).json()
        models = [m["name"] for m in tags.get("models", [])]
        return {"ok": True, "model": MODEL, "model_loaded": any(MODEL in m for m in models)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/extract", dependencies=[Depends(check_key)])
def extract(file: UploadFile = File(...)):
    t0 = time.time()
    try:
        img_b64 = prep_image(file.file.read())
    except Exception:
        raise HTTPException(status_code=400, detail="could not read image")
    raw = call_gemma(read_prompt("extract.txt"), "Extract the data from this report image.", img_b64)
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "model returned invalid JSON", "raw": raw[:2000]})
    data["_ms"] = int((time.time() - t0) * 1000)
    return data


class ExplainReq(BaseModel):
    report_type: str = "lab"
    results: list[dict] = []          # [{name, value, unit, status, ref_low, ref_high}]
    radiology: dict | None = None     # {modality, findings, impression, severity}
    doctor_type: str | None = None    # decided by the backend routing table
    urgent_flags: list[str] = []      # decided by the backend code


@app.post("/explain", dependencies=[Depends(check_key)])
def explain(req: ExplainReq):
    t0 = time.time()
    raw = call_gemma(read_prompt("explain.txt"), json.dumps(req.model_dump(), ensure_ascii=False))
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "model returned invalid JSON", "raw": raw[:2000]})
    data["_ms"] = int((time.time() - t0) * 1000)
    return data
