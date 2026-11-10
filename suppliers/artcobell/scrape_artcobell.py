#!/usr/bin/env python3
"""
Artcobell supplier-catalog pilot scraper — Signature School Products.

Pilot scope (deliberately narrow):
  * Inventories https://www.artcobell.com/sitemap.xml and classifies URLs
    (product/solution pages vs blog / case studies / other).
  * Downloads (and caches) two PDFs:
      1. The Shape Tables technical specifications PDF (artcobell.com)
      2. The Artcobell "List Pricer", February 15, 2025 edition (public copy
         hosted on a state procurement mirror; prices come ONLY from here —
         artcobell.com publishes no prices).
  * Extracts the "Shape Table Tops" rows from the List Pricer's TABLES
    section: model, shape/product group, top material/edge (description),
    size, units per carton, weight (lbs), list price (USD, standard), plus
    the premium/markerboard price and legs-required in the notes.
  * Cross-checks models against the Shape Tables spec PDF (which models it
    documents, its depth x width figures, and its "Model No. X" notes such
    as "Uses 5 legs").
  * Writes output/artcobell_supplier_pilot.csv and output/pilot_summary.md.

Rules honoured:
  * robots.txt is fetched and checked (artcobell.com allows product content,
    disallows /sample-*, previews, /_hcms/preview/, /hs/* preference pages).
  * Honest User-Agent, >=1.2s between live requests, responses cached in
    cache/ so re-runs do not refetch.
  * Nothing is invented: a field that could not be extracted stays blank and
    is explained in the row's `notes`. dealer_cost_usd is always blank —
    dealer cost depends on Signature School Products' own dealer terms,
    which are not published anywhere this scraper reads.

Requirements: Python 3.10+, `requests`; PDF text extraction uses the first
available of: `pdftotext` (poppler-utils, system), `pdfplumber`, `pypdf`.
BeautifulSoup is used for sitemap parsing when available (stdlib XML/regex
fallback otherwise). See README.md for setup (a venv is recommended).

Usage:
    python3 scrape_artcobell.py [--cache-dir cache] [--out-dir output]
                                [--pricer-url URL] [--no-network]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
import time
import urllib.robotparser
from datetime import date
from pathlib import Path

import requests

BASE = "https://www.artcobell.com"
SITEMAP_URL = BASE + "/sitemap.xml"
ROBOTS_URL = BASE + "/robots.txt"
SPEC_PDF_URL = (
    "https://www.artcobell.com/hubfs/Literature/Tech%20Specs/"
    "03_Artcobell_Specifications_ShapeTables_.pdf"
)
# Public copy of the Artcobell List Pricer (Feb 15, 2025), found on the
# Mississippi state procurement document server (SRM.MAGIC.MS.GOV).
PRICER_PDF_URL = (
    "https://SRM.MAGIC.MS.GOV:443/SAP/EBP/DOCSERVER/"
    "ARTCOBELL%20PRICELIST%5F2025%20CONDENSED.PDF"
    "?PHIOGET&KPID=767FE80500261FE08AD6593EC47FC166"
    "&KPCLASS=BBP_P_DOC&SAP-CLIENT=100"
)

SUPPLIER = "Artcobell"
BRAND = "Artcobell"
USER_AGENT = (
    "SignatureSchoolProducts-PilotScraper/0.1 "
    "(+authorized dealer catalog research; contact zach@signatureschoolproducts.com)"
)
REQUEST_DELAY_SECONDS = 1.2

CSV_COLUMNS = [
    "supplier", "supplier_sku_model", "brand", "product_name", "description",
    "supplier_category", "dimensions", "list_price_usd", "dealer_cost_usd",
    "units_per_carton", "weight_lbs", "image_url", "spec_source_url",
    "source_page_url", "last_scraped_date", "notes",
]

# --------------------------------------------------------------------------
# HTTP with cache + politeness
# --------------------------------------------------------------------------

class Fetcher:
    def __init__(self, cache_dir: Path, no_network: bool = False):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.no_network = no_network
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.fetched_live: list[str] = []
        self.from_cache: list[str] = []
        self.errors: list[str] = []

    def _cache_path(self, url: str, suffix: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{digest}{suffix}"

    def get(self, url: str, suffix: str = "") -> bytes | None:
        path = self._cache_path(url, suffix)
        if path.exists() and path.stat().st_size > 0:
            self.from_cache.append(url)
            return path.read_bytes()
        if self.no_network:
            self.errors.append(f"not cached and --no-network set: {url}")
            return None
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                time.sleep(REQUEST_DELAY_SECONDS if attempt == 0 else 5)
                with self.session.get(url, timeout=(15, 300), stream=True) as resp:
                    resp.raise_for_status()
                    chunks = [c for c in resp.iter_content(65536) if c]
                data = b"".join(chunks)
                path.write_bytes(data)
                self.fetched_live.append(url)
                return data
            except Exception as exc:  # noqa: BLE001 - retry once, then degrade
                last_exc = exc
        self.errors.append(f"GET {url} failed after 2 attempts: {last_exc}")
        return None


# --------------------------------------------------------------------------
# PDF text extraction: pdftotext > pdfplumber > pypdf
# --------------------------------------------------------------------------

def pdf_to_pages_text(pdf_path: Path) -> tuple[list[str], str]:
    """Return (per-page text list, extractor name)."""
    # 1) poppler pdftotext -layout (fast, preserves layout + form feeds)
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, timeout=600, check=True,
        )
        text = out.stdout.decode("utf-8", errors="replace")
        if text.strip():
            return text.split("\f"), "pdftotext -layout (poppler)"
    except Exception:
        pass
    # 2) pdfplumber
    try:
        import pdfplumber  # type: ignore

        pages = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        if any(p.strip() for p in pages):
            return pages, "pdfplumber"
    except Exception:
        pass
    # 3) pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        return [(p.extract_text() or "") for p in reader.pages], "pypdf"
    except Exception as exc:
        raise RuntimeError(f"no working PDF text extractor for {pdf_path}: {exc}")


# --------------------------------------------------------------------------
# Sitemap inventory + classification
# --------------------------------------------------------------------------

def parse_sitemap(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, image_urls).

    HubSpot's sitemap interleaves <loc> page entries with namespaced
    <image:loc> entries; a namespace-aware XML parse conflates them, so
    precise regexes on the two distinct tags are more reliable here.
    """
    text = xml_bytes.decode("utf-8", errors="replace")
    pages = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
    images = re.findall(r"<image:loc>\s*([^<]+?)\s*</image:loc>", text)
    return pages, images


def classify_url(url: str) -> str:
    u = url.lower()
    path = re.sub(r"^https?://[^/]+", "", u)
    if "/blog" in path or "research-articles" in path or "/en/" in path and "blog" in path:
        return "blog/article"
    if "case" in path or "/hubfs/" in path:
        return "asset/case-study"
    solution_markers = (
        "classroom", "media-center", "breakout", "learning-hallway",
        "cafeteria", "seating", "table", "desk", "storage", "solution",
        "product", "furniture", "makerspace", "esports", "library",
    )
    if any(m in path for m in solution_markers):
        return "product/solution"
    return "other"


# --------------------------------------------------------------------------
# List Pricer: Shape Table Tops rows
# --------------------------------------------------------------------------

# A Shape Table Tops row, e.g.:
#   DTT-SQ36E  Laminate 1-1/8" core | Banded Flat Edge (E)  36" X 36"  1  2.1
#       58.0  $300  $475  4
ROW_RE = re.compile(
    r"""^\s*(?P<model>DTT-[A-Z0-9]+E)\s+
    (?P<desc>Laminate[^$]*?)\s*
    (?P<size>\d+(?:\.\d+)?\s*"\s*(?:[xX]\s*\d+(?:\.\d+)?\s*")?) \s+
    (?P<units>\d+)\s+(?P<cubes>\d+(?:\.\d+)?)\s+(?P<lbs>\d+(?:\.\d+)?)\s+
    \$(?P<price>[\d,]+)\s+\$(?P<premium>[\d,]+)\s+(?P<legs>\d+)\s*$""",
    re.VERBOSE,
)

HEADING_EXCLUDES = {
    "tables", "shape table tops", "model", "model builder", "notes",
    "application & specification rules", "statement of line",
    "top material | edge", "list price", "size", "required",
}
HEADING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ()\-/&]{1,40}$")

# Canonical Shape Table shape names from the Pricer's Statement of Line.
# Some contain digits ("3P-120", "4P"), which the generic heading heuristic
# rejects, and two appear in the page layout as side annotations
# ("Curved In", "S-Shape Curve") that belong to the canonical group.
SHAPE_HEADINGS = {
    "Chain", "Gem", "Flower", "Square", "Round", "Rectangle", "Aperture",
    "3P-120", "Nova", "Expanse", "Nebula", "Gravity", "Star", "Kidney",
    "Half Round", "Half-Round", "Horseshoe", "4P", "Trapezoid", "Half Moon",
    "Puddle", "Crescent", "Multi-Media", "Chevron", "Curve (S)",
    "Curve (Inside)", "Curve (Outside)", "Curve S", "Curve",
}
HEADING_ALIASES = {
    "Curved In": "Curve (Inside)",
    "Curved Out": "Curve (Outside)",
    "S-Shape Curve": "Curve (S)",
}


def _looks_like_heading(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 42:
        return None
    if any(ch in s for ch in '"$|') or re.search(r"\d", s):
        return None
    if not HEADING_RE.match(s):
        return None
    low = s.lower()
    if low in HEADING_EXCLUDES or low.startswith(("artcobell", "learn more", "use ", "specify", "tops and", "legs")):
        return None
    if low.endswith((".", ",")):
        return None
    return s


def parse_pricer_shape_table_tops(pages: list[str]) -> list[dict]:
    """Extract Shape Table Tops rows from List Pricer page texts."""
    rows: list[dict] = []
    in_section = False
    heading: str | None = None
    pending_model_line: str | None = None  # wrapped row, first half

    for page in pages:
        lines = page.splitlines()
        page_is_shape_tops = any("Shape Table Tops" in ln for ln in lines[:6])
        if page_is_shape_tops:
            in_section = True
        elif in_section and lines and "TABLES" in lines[0] and "Shape Table Tops" not in page[:2000]:
            # A later TABLES page that is not Shape Table Tops ends the slice
            # (leg kits, activity tables, ... are out of pilot scope).
            if any(("Leg Kit" in ln or "Activity Table" in ln) for ln in lines[:6]):
                in_section = False
        if not in_section:
            continue

        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            m = ROW_RE.match(raw)
            if m:
                d = m.groupdict()
                rows.append({
                    "model": d["model"],
                    "group": heading or "",
                    "description": " ".join(d["desc"].split()).rstrip(","),
                    "size": " ".join(d["size"].split()),
                    "units": d["units"],
                    "cubes": d["cubes"],
                    "lbs": d["lbs"],
                    "price": d["price"].replace(",", ""),
                    "premium": d["premium"].replace(",", ""),
                    "legs": d["legs"],
                    "wrapped": bool(pending_model_line),
                })
                pending_model_line = None
                continue
            # Wrapped row: model starts a line that does not complete;
            # join with following lines until ROW_RE matches.
            if re.match(r"^\s*DTT-[A-Z0-9]+E\b", raw):
                pending_model_line = raw
                continue
            if pending_model_line is not None:
                joined = pending_model_line.rstrip() + " " + line
                m2 = ROW_RE.match(joined)
                if m2:
                    d = m2.groupdict()
                    rows.append({
                        "model": d["model"], "group": heading or "",
                        "description": " ".join(d["desc"].split()).rstrip(","),
                        "size": " ".join(d["size"].split()),
                        "units": d["units"], "cubes": d["cubes"],
                        "lbs": d["lbs"],
                        "price": d["price"].replace(",", ""),
                        "premium": d["premium"].replace(",", ""),
                        "legs": d["legs"], "wrapped": True,
                    })
                    pending_model_line = None
                    continue
                if len(joined) > 400:
                    pending_model_line = None
                else:
                    pending_model_line = joined
                continue
            if line in HEADING_ALIASES:
                heading = HEADING_ALIASES[line]
                continue
            if line in SHAPE_HEADINGS:
                heading = line
                continue
            h = _looks_like_heading(raw)
            if h:
                heading = h
    # De-duplicate by model (keep first sighting)
    seen, unique = set(), []
    for r in rows:
        if r["model"] not in seen:
            seen.add(r["model"])
            unique.append(r)
    return unique


# --------------------------------------------------------------------------
# Shape Tables spec PDF: model cross-check + notes
# --------------------------------------------------------------------------

SPEC_ROW_RE = re.compile(
    r"^\s*(?P<model>(?:DTT|DTLP|SS|TA)-[A-Z0-9]+)\s+"
    r"(?P<d1>\d+(?:\.\d+)?)\s*[\"”]\s+(?P<d2>\d+(?:\.\d+)?)\s*[\"”]"
)
SPEC_NOTE_START = re.compile(r"Model No\.\s*((?:DTT|DTLP|SS|TA)-[A-Z0-9]+)\s*:")


def parse_spec_pdf(pages: list[str]) -> dict[str, dict]:
    """Per-model: spec depth x width (first table sighting) + note bullets."""
    info: dict[str, dict] = {}
    current: str | None = None
    for page in pages:
        for raw in page.splitlines():
            line = raw.strip()
            m = SPEC_ROW_RE.match(raw)
            if m:
                entry = info.setdefault(m.group("model"), {"dims": "", "notes": []})
                if not entry["dims"]:
                    entry["dims"] = f'{m.group("d1")}" x {m.group("d2")}" (spec depth x width)'
            nm = SPEC_NOTE_START.search(line)
            if nm:
                current = nm.group(1)
                info.setdefault(current, {"dims": "", "notes": []})
                continue
            if current and line.startswith("•") and len(line) > 3:
                note = line.lstrip("• ").strip()
                entry = info[current]
                if note and note not in entry["notes"]:
                    entry["notes"].append(note)
            elif current and not line.startswith(("•", "Table top", "Tabletop")):
                # keep collecting wrapped bullet continuations is overkill;
                # stop at obvious new sections
                if re.match(r"^(Learn more|Artcobell)", line):
                    current = None
    return info


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--pricer-url", default=PRICER_PDF_URL)
    ap.add_argument("--no-network", action="store_true",
                    help="use only files already in the cache")
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent
    cache_dir = base_dir / args.cache_dir
    out_dir = base_dir / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(cache_dir, no_network=args.no_network)
    today = date.today().isoformat()
    errors: list[str] = list(fetcher.errors)

    # --- robots.txt ------------------------------------------------------
    robots_bytes = fetcher.get(ROBOTS_URL, ".txt")
    robots_ok = robots_bytes is not None
    rp = urllib.robotparser.RobotFileParser()
    if robots_bytes:
        rp.parse(robots_bytes.decode("utf-8", errors="replace").splitlines())

    def allowed(url: str) -> bool:
        return rp.can_fetch(USER_AGENT, url) if robots_ok else True

    # --- sitemap inventory ----------------------------------------------
    sitemap_bytes = fetcher.get(SITEMAP_URL, ".xml")
    urls: list[str] = []
    image_urls: list[str] = []
    if sitemap_bytes:
        urls, image_urls = parse_sitemap(sitemap_bytes)
    else:
        errors.append("sitemap.xml could not be fetched")
    classes: dict[str, list[str]] = {}
    for u in urls:
        classes.setdefault(classify_url(u), []).append(u)
    page_urls = [u for u in urls if u.startswith(BASE) and not u.lower().endswith(
        (".jpg", ".jpeg", ".png", ".svg", ".gif", ".pdf", ".webp"))]
    disallowed = [u for u in page_urls if not allowed(u)]

    # Image candidates come from the sitemap's <image:loc> entries; match
    # per-model only when a model token appears in the URL — otherwise
    # image_url stays blank rather than guessing.

    def find_image(model: str) -> str:
        token = model.removeprefix("DTT-").removesuffix("E")
        for u in image_urls:
            if token and token.lower() in u.lower():
                return u
        return ""

    # --- PDFs -------------------------------------------------------------
    spec_path = fetcher._cache_path(SPEC_PDF_URL, ".pdf")
    if fetcher.get(SPEC_PDF_URL, ".pdf") is None:
        errors.append("Shape Tables spec PDF could not be fetched")
    pricer_path = fetcher._cache_path(args.pricer_url, ".pdf")
    pricer_bytes = fetcher.get(args.pricer_url, ".pdf")
    pricer_ok = pricer_bytes is not None
    if not pricer_ok:
        errors.append("List Pricer PDF could not be fetched — prices will be blank")

    pricer_rows: list[dict] = []
    pricer_extractor = ""
    if pricer_ok:
        try:
            pages, pricer_extractor = pdf_to_pages_text(pricer_path)
            pricer_rows = parse_pricer_shape_table_tops(pages)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"List Pricer parsing failed: {exc}")

    spec_info: dict[str, dict] = {}
    spec_extractor = ""
    if spec_path.exists():
        try:
            pages, spec_extractor = pdf_to_pages_text(spec_path)
            spec_info = parse_spec_pdf(pages)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Spec PDF parsing failed: {exc}")

    # --- Build CSV rows ----------------------------------------------------
    out_rows = []
    for r in pricer_rows:
        spec = spec_info.get(r["model"], {})
        notes = [
            f"List price is Standard (laminate); Premium/Markerboard list ${int(r['premium']):,}.",
            f"Legs required: {r['legs']} (legs priced/specified separately, DTLP leg kits).",
            f"Cubes each: {r['cubes']}.",
            "Price source: Artcobell List Pricer, Feb 15 2025 edition (public procurement copy); verify against current dealer pricer before quoting.",
            "dealer_cost_usd blank: dealer terms not published.",
        ]
        if r.get("wrapped"):
            notes.append("Row was wrapped across two lines in the PDF; joined during parsing.")
        if spec:
            notes.append("Model also documented in Shape Tables spec PDF"
                         + (f' (spec dims: {spec["dims"]}).' if spec.get("dims") else "."))
            for n in spec.get("notes", [])[:2]:
                notes.append(f"Spec note: {n}")
        else:
            notes.append("Model not found in Shape Tables spec PDF text extraction.")
        img = find_image(r["model"])
        if not img:
            notes.append("image_url blank: no per-model image reliably matched in pilot.")
        group = r["group"]
        out_rows.append({
            "supplier": SUPPLIER,
            "supplier_sku_model": r["model"],
            "brand": BRAND,
            "product_name": f"{group} Shape Table Top".strip() if group else "Shape Table Top",
            "description": f"{r['description']} — shape table top (top only; legs specified separately).",
            "supplier_category": "Tables > Shape Table Tops" + (f" > {group}" if group else ""),
            "dimensions": r["size"],
            "list_price_usd": r["price"],
            "dealer_cost_usd": "",
            "units_per_carton": r["units"],
            "weight_lbs": r["lbs"],
            "image_url": img,
            "spec_source_url": SPEC_PDF_URL,
            "source_page_url": args.pricer_url,
            "last_scraped_date": today,
            "notes": " ".join(notes),
        })

    csv_path = out_dir / "artcobell_supplier_pilot.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    # --- Summary ------------------------------------------------------------
    def populated(field: str) -> int:
        return sum(1 for r in out_rows if str(r.get(field, "")).strip())

    summary = [
        "# Artcobell pilot — summary",
        "",
        f"Run date: {today}",
        f"Scraper: scrape_artcobell.py (User-Agent: {USER_AGENT})",
        "",
        "## Inventory (artcobell.com/sitemap.xml)",
        f"- robots.txt fetched: {'yes' if robots_ok else 'NO'} "
        "(allows product content; disallows /sample-*, previews, /hs/*).",
        f"- Total page URLs in sitemap: {len(urls)} "
        f"(plus {len(image_urls)} image URLs in <image:loc> entries)",
    ]
    for cls in sorted(classes):
        summary.append(f"  - {cls}: {len(classes[cls])}")
    summary += [
        f"- Page URLs checked against robots.txt: {len(page_urls)}; "
        f"disallowed: {len(disallowed)} (none were fetched).",
        "",
        "## Sources used",
        f"- Shape Tables spec PDF: {SPEC_PDF_URL} "
        f"({'extracted with ' + spec_extractor if spec_extractor else 'NOT extracted'}) "
        f"— {len(spec_info)} models cross-referenced.",
        f"- List Pricer PDF (Feb 15, 2025): {args.pricer_url} "
        f"({'accessible, extracted with ' + pricer_extractor if pricer_ok and pricer_extractor else 'NOT accessible/extracted'})",
        "- PILOT SLICE: only the Pricer's TABLES > Shape Table Tops pages "
        "were parsed for product rows. All other Pricer categories "
        "(Soft Seating, Seating, Student Desks, other Tables sub-sections, "
        "Teacher Stations) are inventoried but not yet extracted.",
        "",
        f"## Output",
        f"- Rows written: {len(out_rows)} (output/artcobell_supplier_pilot.csv)",
        "- Field coverage (populated / total):",
    ]
    for col in CSV_COLUMNS:
        summary.append(f"  - {col}: {populated(col)}/{len(out_rows)}")
    summary += [
        "",
        "## Known gaps",
        "- dealer_cost_usd: always blank — Signature's dealer discount terms "
        "are not published; must come from the current dealer pricer/agreement.",
        "- image_url: blank unless a sitemap image URL contains the model "
        "token; per-model image matching (HubSpot /hubfs/Product/ folders) "
        "is a full-run task.",
        "- Prices are LIST prices from the Feb 15, 2025 Pricer found on a "
        "public procurement mirror — treat as pilot data and re-verify "
        "against the current official dealer pricer before quoting anyone.",
        "- Product descriptions on artcobell.com are written per collection, "
        "not per model; the CSV description is the Pricer's material/edge "
        "specification for each model, not marketing copy.",
        "- Options encoded in model suffixes (laminate, edge, frame colors) "
        "are not expanded into variant rows in the pilot.",
        "",
        "## Errors encountered",
    ]
    summary += [f"- {e}" for e in (errors + fetcher.errors)] or ["- none"]
    summary += [
        "",
        "## Fetch log",
        f"- Downloaded live this run: {len(fetcher.fetched_live)}",
        f"- Served from cache: {len(fetcher.from_cache)}",
    ]
    (out_dir / "pilot_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print(f"rows={len(out_rows)} csv={csv_path}")
    print(f"sitemap_urls={len(urls)} classes={ {k: len(v) for k, v in classes.items()} }")
    print(f"spec_models={len(spec_info)} pricer_ok={pricer_ok} extractors: pricer={pricer_extractor!r} spec={spec_extractor!r}")
    if errors or fetcher.errors:
        print("errors:", "; ".join(errors + fetcher.errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
