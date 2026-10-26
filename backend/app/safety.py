# =============================================================================
# safety.py
# Purpose : Code-level safety rules applied AFTER the model answers, so the
#           model alone never decides whether a result looks "fine".
# Logic   : 1) Labs: compare the value with the normal range printed on the
#              paper. The final color is the WORSE of (model color, code color),
#              so code can raise a warning but never hide one.
#           2) Radiology: scan the original report wording for urgent words
#              (mass, hemorrhage, fracture...). A hit forces RED, unless the
#              word is negated nearby ("no focal mass").
#           3) Overall color = the worst color among all cards.
# Tuning  : Change the thresholds / word list below. Have a doctor review them
#           before real users rely on the app.
# =============================================================================
import re

from .schemas import LabResult, LlmOutput, RadiologyResult, Report, Status

_RANK = {"green": 0, "yellow": 1, "red": 2}

# Two-sided range (low-high): outside by more than 60% of the range width -> red
TWO_SIDED_RED = 0.6
# One-sided range (< x or > x): outside by more than 50% of the bound -> red
ONE_SIDED_RED = 0.5

# Words that force a RED radiology card (regex pieces; Arabic words are matched as-is)
_URGENT_TERMS = [
    r"mass(?:es)?", r"h(?:a)?emorrhag\w*", r"bleed\w*", r"fracture\w*", r"tumou?rs?",
    r"malignan\w*", r"metasta\w*", r"carcinoma", r"cancer\w*", r"pneumothorax",
    r"embol\w*", r"aneurysm\w*", r"infarct\w*", r"perforat\w*", r"abscess\w*",
    "ورم", "أورام", "نزيف", "كسر", "كتلة", "خبيث",
]

# Negation words that cancel an urgent word when they appear just before it
_NEGATION = r"no|without|negative\s+for|free\s+of|absence\s+of|absent|lack\s+of|لا|بدون|عدم|مفيش|مافيش"
_NEG_BEFORE = re.compile(rf"(?<!\w)(?:{_NEGATION})(?:\s+\w+){{0,3}}\s*$", re.IGNORECASE)


def _compile_term(term: str) -> re.Pattern:
    """Compile one urgent word (English words need word boundaries)."""
    pattern = rf"(?<!\w){term}(?!\w)" if term.isascii() else term
    return re.compile(pattern, re.IGNORECASE)


_URGENT_RE = [_compile_term(t) for t in _URGENT_TERMS]

_DEFAULT_SUMMARY = {
    "green": "نتايجك كويسة.",
    "yellow": "فيه حاجات بسيطة محتاجة متابعة.",
    "red": "فيه حاجات محتاجة تكلم دكتور في أقرب وقت.",
}


def normalize_status(raw: str) -> Status:
    """Map any status word from the model to green/yellow/red (unknown -> yellow)."""
    s = raw.strip().lower()
    if s in {"green", "good", "normal", "ok"}:
        return "green"
    if s in {"red", "bad", "urgent", "high", "critical"}:
        return "red"
    return "yellow"


def worst(a: Status, b: Status) -> Status:
    """Return the more serious of two statuses."""
    return a if _RANK[a] >= _RANK[b] else b


def parse_number(text: str) -> float | None:
    """Extract the first number from a value like '10.2', '7,500' or '١٠٫٢'."""
    s = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789."))
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)  # 7,500 -> 7500
    s = s.replace(",", ".")                          # 10,2 -> 10.2
    match = re.search(r"\d+(?:\.\d+)?", s)
    return float(match.group()) if match else None


def status_from_range(value_text: str, low: float | None, high: float | None) -> Status | None:
    """Judge a value against the printed range. None = cannot judge (no number/range)."""
    value = parse_number(value_text)
    if value is None or (low is None and high is None):
        return None

    if low is not None and high is not None:
        if high <= low:  # inconsistent range (probably misread) -> do not judge
            return None
        if low <= value <= high:
            return "green"
        gap = (low - value) if value < low else (value - high)
        return "red" if gap / (high - low) > TWO_SIDED_RED else "yellow"

    # One-sided range
    if high is not None:
        gap, bound = value - high, high
    else:
        gap, bound = low - value, low
    if gap <= 0:
        return "green"
    return "red" if gap / (abs(bound) or 1) > ONE_SIDED_RED else "yellow"


def format_range(low: float | None, high: float | None) -> str:
    """Write the printed range in simple Arabic, or '' if there is none."""
    if low is not None and high is not None:
        return f"من {low:g} لـ {high:g}"
    if high is not None:
        return f"لحد {high:g}"
    if low is not None:
        return f"من {low:g} وأكتر"
    return ""


def find_urgent_terms(text: str) -> list[str]:
    """Return urgent words found in the text that are NOT negated right before them."""
    found: list[str] = []
    for regex in _URGENT_RE:
        for match in regex.finditer(text):
            before = text[max(0, match.start() - 40):match.start()]
            if _NEG_BEFORE.search(before):
                continue  # e.g. "no focal mass"
            found.append(match.group(0).lower())
            break
    return found


def build_report(out: LlmOutput, has_labs: bool, has_rads: bool) -> Report:
    """Turn the model answer into the final report, applying all safety rules."""
    results: list[LabResult] = []
    if has_labs:  # ignore labs the model invented when no lab image was sent
        for lab in out.labs:
            if not lab.name:
                continue
            status = normalize_status(lab.status)
            by_range = status_from_range(lab.value, lab.ref_low, lab.ref_high)
            if by_range:
                status = worst(status, by_range)
            text = lab.explanation
            printed = format_range(lab.ref_low, lab.ref_high)
            if printed:
                text = f"{text} المدى الطبيعي المكتوب في ورقتك: {printed}.".strip()
            results.append(LabResult(name=lab.name, value=lab.value, unit=lab.unit,
                                     status=status, explanation=text))

    radiology: list[RadiologyResult] = []
    urgent_hits: list[str] = []
    if has_rads:  # ignore radiology the model invented when no report image was sent
        for rad in out.radiology:
            if not (rad.type or rad.findings):
                continue
            status = normalize_status(rad.status)
            hits = find_urgent_terms(rad.original_text or rad.findings)
            text = rad.explanation
            if hits:
                status = "red"
                urgent_hits.extend(hits)
                text = f"تنبيه: التقرير فيه ({hits[0]}) ومحتاج دكتور في أقرب وقت. {text}".strip()
            radiology.append(RadiologyResult(type=rad.type or "تقرير أشعة", findings=rad.findings,
                                             status=status, explanation=text))

    overall: Status = "green"
    for item in [*results, *radiology]:
        overall = worst(overall, item.status)

    summary = out.summary or _DEFAULT_SUMMARY[overall]
    if urgent_hits:
        summary = f"تنبيه: فيه حاجات في تقرير الأشعة محتاجة دكتور في أقرب وقت. {summary}"

    return Report(overall=overall, summary=summary, results=results, radiology=radiology,
                  doctor=out.doctor, questions=out.questions[:5])
