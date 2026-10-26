# Tahlili (تحليلي)

Snap a photo of a lab report and get a color-coded card in Egyptian Arabic: each result marked normal / high / low, a plain-language explanation, the type of doctor to see, a priority level, and questions to ask the doctor.

> **Not a diagnosis.** Tahlili explains the numbers only. No diagnosis, no medication, no dosages. The demo runs on sample data only.

Built for a hackathon with open-source AI (Gemma 4).

## How it works

```
Photo of report -> /extract (Gemma 4 reads it) -> rules in code -> /explain (Gemma 4 explains) -> card
```

- **Gemma 4 E4B** (open-source, multimodal) runs through **Ollama** on a Colab T4 GPU. It reads the image directly, so there is no separate OCR step. No fine-tuning.
- The model only **reads and explains**. It never decides the verdict.
- **Status (normal/high/low), urgent flags and doctor routing are computed by deterministic code**, so the model can't invent numbers or change a result.
- Arabic audio ("listen to the explanation") uses the browser's Web Speech API, so it adds no load on the server.

## Repo layout

| Path | What it is |
|------|------------|
| `ai/colab_server.py` | FastAPI server for the AI part: `GET /health`, `POST /extract`, `POST /explain` |
| `ai/prompts/extract.txt` | Prompt for reading the report image |
| `ai/prompts/explain.txt` | Prompt for the Egyptian Arabic explanation |
| `ai/sample_explain_input.json` | Sample input for `/explain` |
| `contract/` | Sample data showing the request/response shape |
| `tahlili_colab.ipynb` | Notebook that starts Ollama, the server and a Cloudflare tunnel on Colab |
| `backend/`, `frontend/` | Web app (see "Backend and frontend" below) |

## AI API

Every request needs the header `X-API-KEY: <key>`. The server URL is a Cloudflare quick tunnel and **changes whenever the server cell is restarted**.

### `GET /health`
Returns `ok` when the server is up.

### `POST /extract`
Multipart form, field `file` = the report image.

```json
{
  "report_type": "lab | radiology | other",
  "tests": [
    {"name": "Hemoglobin", "value": 14.2, "value_text": null,
     "unit": "g/dL", "ref_low": 13.5, "ref_high": 17.5, "ref_text": "13.5 - 17.5"}
  ],
  "radiology": null
}
```

For radiology reports, `radiology` is `{modality, body_part, findings[], impression}`.

### `POST /explain`
JSON body:

```json
{
  "report_type": "lab",
  "results": [{"name": "Hemoglobin", "value": 10.1, "unit": "g/dL",
               "status": "low", "ref_low": 13.5, "ref_high": 17.5}],
  "radiology": null,
  "doctor_type": "Internal medicine / Hematology",
  "urgent_flags": []
}
```

Response:

```json
{
  "summary": ["line 1", "line 2", "line 3"],
  "explanations": [{"name": "Hemoglobin", "text": "..."}],
  "pattern": "...",
  "priority": "normal | follow_up | see_doctor_soon",
  "doctor_questions": ["..."]
}
```

`status`, `urgent_flags` and `doctor_type` are computed by the backend before calling `/explain`.

Typical latency is 20 to 90 seconds per request (images are downscaled to about 1400px before sending), so clients should show a loading state and use a timeout of at least 120 seconds.

## Safety by design

- No diagnosis, no medication, no dosages.
- Verdicts and urgent alerts come from code, never from the LLM.
- X-ray image analysis (marking fractures or tumors on the image) is **intentionally left out**: Gemma is a general model, not a medical one, and a wrong location could cause harm. Only written radiology reports are read and explained.

## Run the AI server (Colab)

1. Open `tahlili_colab.ipynb` in Google Colab with a T4 GPU.
2. Set `API_KEY` (and `REPO_URL`) in the config cell.
3. Run the cells in order: install, Ollama, clone, server + tunnel.
4. Copy the `trycloudflare.com` URL from the server cell output and check `<url>/health`.
5. Keep the keep-alive cell running and don't restart the server cell, or the URL will change.

## Backend and frontend

The FastAPI backend accepts lab and written radiology report photos at `POST /analyze`. It sends each image to the configured AI server's `/extract` endpoint, applies range and urgent-word checks in code, then asks `/explain` for the Arabic summary. Uploaded images are held in memory.

Run the backend from PowerShell:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Configure `backend/.env` with `LLM_API_URL` set to the AI server root URL and `LLM_API_KEY` set to the same key used by the Colab server. Existing URLs ending in `/v1` are also accepted. The backend reads `backend/.env` regardless of the current working directory. The AI server model is configured on the AI server itself.

Open `tahlili.html` in a browser after starting the backend. The page sends `lab_images` and `radiology_images` to `http://localhost:8000/analyze` and displays the returned report.

## Roadmap

- Annotated imaging with a certified medical model (e.g. MedGemma).
- Offline mode with a smaller on-device model.
- Support for more report types and more test-name aliases.

## Team

- TODO: names

## Disclaimer

Tahlili is a hackathon prototype. It is not a medical device and does not replace a doctor. Always consult a qualified doctor about your results.
