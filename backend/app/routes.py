# =============================================================================
# routes.py
# Purpose : The API endpoint the frontend calls: POST /analyze.
# Logic   : receive images -> validate -> send to model -> apply safety rules
#           -> return the report JSON. Field names (lab_images, radiology_images)
#           and the response shape match tahlili.html exactly.
# Privacy : Images and results are never saved or logged.
# =============================================================================
from fastapi import APIRouter, File, HTTPException, UploadFile

from .config import settings
from .images import read_images
from .model_client import ModelError, analyze_images
from .safety import build_report
from .schemas import Report

router = APIRouter()


@router.post("/analyze", response_model=Report)
async def analyze(
    lab_images: list[UploadFile] | None = File(None),
    radiology_images: list[UploadFile] | None = File(None),
) -> Report:
    """Analyze lab/radiology report photos and return a simple Arabic report."""
    lab_files = lab_images or []
    rad_files = radiology_images or []

    if not lab_files and not rad_files:
        raise HTTPException(400, "ابعت صورة واحدة على الأقل.")
    if len(lab_files) + len(rad_files) > settings.max_images_total:
        raise HTTPException(400, f"الحد الأقصى {settings.max_images_total} صور في المرة.")

    lab_urls = await read_images(lab_files)
    rad_urls = await read_images(rad_files)

    try:
        llm_out = await analyze_images(lab_urls, rad_urls)
    except ModelError:
        raise HTTPException(502, "مقدرناش نحلل الصور دلوقتي، جرب تاني بعد شوية.")

    report = build_report(llm_out, has_labs=bool(lab_urls), has_rads=bool(rad_urls))
    if not report.results and not report.radiology:
        raise HTTPException(422, "مقدرناش نقرا نتايج من الصور، جرب صورة أوضح.")
    return report
