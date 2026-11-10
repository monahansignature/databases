#!/usr/bin/env python3
"""
Artcobell supplier-catalog expansion — Signature School Products.

Expands the 44-row pilot (output/artcobell_supplier_pilot.csv, Shape Table
Tops only) to 100 rows by extracting additional, fully priced model rows
from the SAME source: the Artcobell List Pricer, February 15, 2025 edition
(public procurement copy already in cache/).

New sections extracted (all TABLES chapter of the Pricer):
  * Adjustable Post Leg Kits  (pricer p.88)  — DTLP-4AJP / 4ATP / 4ASP rows
  * Fixed Post Leg Kits       (pricer p.89)  — DTLP-4F* rows (incl. wheelbarrow)
  * Adjustable T-Leg Kits     (pricer p.90)  — first DTLT-2AJ18 group (3 rows)
  * Tables Accessories        (pricer p.91)  — TA-CPS4, TA-CPMS50T4 (caster
    packs), TA-GFK (felt glide pack), TA-SA1224.F / TA-SA1236.F (screens)

Output: output/artcobell_supplier_100.csv = original 44 pilot rows (verbatim)
+ 56 new rows. The original pilot CSV is never modified.

Rules (same as pilot): nothing invented — every price/dimension/weight comes
from the Pricer text; dealer_cost_usd stays blank (dealer terms unpublished);
image_url stays blank for new rows (no per-model image reliably matched).
New rows use last_scraped_date 2026-11-10.

Usage: python3 scrape_artcobell_expand.py [--cache-dir cache] [--out-dir output]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
from pathlib import Path

PRICER_PDF_URL = (
    "https://SRM.MAGIC.MS.GOV:443/SAP/EBP/DOCSERVER/"
    "ARTCOBELL%20PRICELIST%5F2025%20CONDENSED.PDF"
    "?PHIOGET&KPID=767FE80500261FE08AD6593EC47FC166"
    "&KPCLASS=BBP_P_DOC&SAP-CLIENT=100"
)
SPEC_PDF_URL = (
    "https://www.artcobell.com/hubfs/Literature/Tech%20Specs/"
    "03_Artcobell_Specifications_ShapeTables_.pdf"
)
SUPPLIER = BRAND = "Artcobell"
EXPANSION_DATE = "2026-11-10"
CSV_COLUMNS = [
    "supplier", "supplier_sku_model", "brand", "product_name", "description",
    "supplier_category", "dimensions", "list_price_usd", "dealer_cost_usd",
    "units_per_carton", "weight_lbs", "image_url", "spec_source_url",
    "source_page_url", "last_scraped_date", "notes",
]
PRICE_NOTE = ("Price source: Artcobell List Pricer, Feb 15 2025 edition "
              "(public procurement copy); verify against current dealer "
              "pricer before quoting.")
DEALER_NOTE = "dealer_cost_usd blank: dealer terms not published."
IMAGE_NOTE = "image_url blank: no per-model image reliably matched in expansion."
Q = '["\u201d]'  # straight or curly double quote as extracted by pdftotext


def pdf_pages(pdf_path: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, timeout=600, check=True)
    return out.stdout.decode("utf-8", errors="replace").split("\f")


def norm(s: str) -> str:
    """Normalize curly quotes to straight and collapse whitespace."""
    return " ".join(s.replace("\u201d", '"').replace("\u201c", '"').split())


# ---------------------------------------------------------------------------
# Parsers — one per Pricer page layout. Each returns raw dicts.
# ---------------------------------------------------------------------------

ADJ_RE = re.compile(
    rf"^\s*(?P<model>DTLP-[\w.]+)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>\d+\s*{Q}\s*-\s*\d+\s*{Q})\s+(?P<units>4-Legs)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

FIXED_RE = re.compile(
    r"^\s*(?P<model>DTLP-[\w.]+)\s+(?P<desc>.+?)\s{2,}"
    r"(?P<units>4-Legs)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    r"\$(?P<price>[\d,]+)\s*$")

TLEG_RE = re.compile(
    rf"^\s*(?P<model>DTLT-[\w.]+)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>\d+\s*{Q}\s*-\s*\d+\s*{Q})\s+(?P<units>2-Legs)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

CASTER_RE = re.compile(
    r"^\s*(?P<model>TA-CP[\w.]+)\s+(?P<desc>.+?)\s{2,}"
    r"(?P<units>4-pack)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    r"\$(?P<price>[\d,]+)\s*$")

FELT_RE = re.compile(
    r"^\s*(?P<model>TA-GFK)\s+(?P<desc>100-Pack)\s+(?P<units>100)\s+"
    r"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

SCREEN_RE = re.compile(
    rf"^\s*(?P<model>TA-SA[\w.]+)\s+(?P<size>\d+{Q}h\s*x\s*\d+{Q}w)\s+"
    rf"(?P<units>\d+)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    rf"\$(?P<price>[\d,]+)\s*$")


def find_page(pages: list[str], *markers: str) -> str:
    for p in pages:
        if all(mk in p for mk in markers):
            return p
    raise RuntimeError(f"pricer page containing {markers!r} not found")


def parse_table(page: str, regex: re.Pattern) -> list[dict]:
    out, group = [], None
    for raw in page.splitlines():
        line = raw.strip()
        # Track subgroup headings (lines ending in "Legs | ..." style labels)
        if "|" in line and not line.startswith((">", "Model")) \
                and not regex.match(raw) and "Diameter" in line or \
                ("Legs |" in line and "Model" not in line):
            group = line.split("|")[0].strip()
        m = regex.match(raw)
        if m:
            d = m.groupdict()
            d["group"] = group or ""
            out.append(d)
    return out


def base_row(model: str) -> dict:
    return {c: "" for c in CSV_COLUMNS} | {
        "supplier": SUPPLIER, "supplier_sku_model": model, "brand": BRAND,
        "dealer_cost_usd": "", "image_url": "",
        "source_page_url": PRICER_PDF_URL,
        "last_scraped_date": EXPANSION_DATE,
    }


def leg_notes(cubes: str, extra: str = "") -> str:
    parts = [
        "Legs and tops are specified and priced separately "
        "(use with DTT shape table tops).",
        f"Cubes each: {cubes}.",
        PRICE_NOTE, DEALER_NOTE, IMAGE_NOTE,
    ]
    if extra:
        parts.insert(1, extra)
    return " ".join(parts)


def build_rows(pages: list[str]) -> list[dict]:
    rows: list[dict] = []

    # --- Adjustable Post Leg Kits (pricer p.88) --------------------------
    page = find_page(pages, "Adjustable Post Leg Kits")
    for d in parse_table(page, ADJ_RE):
        r = base_row(d["model"])
        r.update({
            "product_name": "Shape Table Leg Kit",
            "description": f"{norm(d['desc'])} — adjustable post leg kit "
                           "(set of 4 legs) for DTT shape table tops; tops "
                           "and legs specified separately.",
            "supplier_category": "Tables > Leg Kits > Adjustable Post Leg Kits",
            "dimensions": norm(d["height"]),
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "spec_source_url": SPEC_PDF_URL,
            "notes": leg_notes(d["cubes"],
                               "Leg options (heights/glide) also documented "
                               "in Shape Tables spec PDF."),
        })
        rows.append(r)

    # --- Fixed Post Leg Kits (pricer p.89) -------------------------------
    page = find_page(pages, "Fixed Post Leg Kits")
    for d in parse_table(page, FIXED_RE):
        desc = norm(d["desc"])
        hm = re.match(r'(\d+)"', desc)
        r = base_row(d["model"])
        r.update({
            "product_name": "Shape Table Leg Kit",
            "description": f"{desc} — fixed post leg kit (set of 4 legs) "
                           "for DTT shape table tops; tops and legs "
                           "specified separately.",
            "supplier_category": "Tables > Leg Kits > Fixed Post Leg Kits",
            "dimensions": f'{hm.group(1)}"' if hm else "",
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "spec_source_url": SPEC_PDF_URL,
            "notes": leg_notes(d["cubes"],
                               "Fixed leg height is stated in the Pricer "
                               "description; recorded in dimensions."),
        })
        rows.append(r)

    # --- Adjustable T-Leg Kits (pricer p.90) — first group only ----------
    page = find_page(pages, "Adjustable T-Leg Kits")
    tlegs = parse_table(page, TLEG_RE)
    for d in tlegs[:3]:  # 18" spread, Juvenile Height group: .4 / .7 / .W
        r = base_row(d["model"])
        r.update({
            "product_name": "T-Leg Table Kit",
            "description": f"{norm(d['desc'])} — adjustable T-leg kit "
                           "(set of 2 legs) for square and rectangle DTT "
                           "tops; tops and legs specified separately.",
            "supplier_category": "Tables > Leg Kits > Adjustable T-Leg Kits",
            "dimensions": norm(d["height"]),
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "spec_source_url": SPEC_PDF_URL,
            "notes": leg_notes(d["cubes"]),
        })
        rows.append(r)

    # --- Tables Accessories (pricer p.91) --------------------------------
    page = find_page(pages, "Caster Pack", "Felt Glide Pack",
                     "Shape Table Screens")
    for d in parse_table(page, CASTER_RE):
        r = base_row(d["model"])
        r.update({
            "product_name": "Caster Pack",
            "description": f"{norm(d['desc'])} — locking caster pack for "
                           "shape table legs; field installed only.",
            "supplier_category": "Tables > Accessories > Caster Pack",
            "dimensions": "",
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": " ".join([
                f"Cubes each: {d['cubes']}.",
                "dimensions blank: Pricer gives no overall dimensions for "
                "this accessory (50mm caster size is in the description).",
                PRICE_NOTE, DEALER_NOTE, IMAGE_NOTE]),
        })
        rows.append(r)
    for d in parse_table(page, FELT_RE):
        r = base_row(d["model"])
        r.update({
            "product_name": "Felt Glide Pack",
            "description": "Felt glide pack (100-pack) — for use with DTLP "
                           "legs, field installed only; 3/8\"-16 x 1\" "
                           "threaded stem.",
            "supplier_category": "Tables > Accessories > Felt Glide Pack",
            "dimensions": "",
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": " ".join([
                f"Cubes each: {d['cubes']}.",
                "dimensions blank: Pricer gives no dimensions for this "
                "accessory (pack size is in the description).",
                PRICE_NOTE, DEALER_NOTE, IMAGE_NOTE]),
        })
        rows.append(r)
    for d in parse_table(page, SCREEN_RE):
        r = base_row(d["model"])
        r.update({
            "product_name": "Shape Table Screen",
            "description": "Clear, frosted acrylic screen panel — use on "
                           "rectangular tops as a privacy screen or modesty "
                           "panel; includes screen, brackets and hardware; "
                           "field installed.",
            "supplier_category": "Tables > Accessories > Shape Table Screens",
            "dimensions": norm(d["size"]),
            "list_price_usd": d["price"].replace(",", ""),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": " ".join([
                f"Cubes each: {d['cubes']}.",
                "Description is the Pricer's Shape Table Screens "
                "specification rules for this model (no per-model "
                "description is published).",
                PRICE_NOTE, DEALER_NOTE, IMAGE_NOTE]),
        })
        rows.append(r)

    # De-duplicate by model, keep first
    seen, unique = set(), []
    for r in rows:
        if r["supplier_sku_model"] not in seen:
            seen.add(r["supplier_sku_model"])
            unique.append(r)
    return unique


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out-dir", default="output")
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent
    cache_dir, out_dir = base_dir / args.cache_dir, base_dir / args.out_dir
    pricer_path = cache_dir / (
        hashlib.sha256(PRICER_PDF_URL.encode()).hexdigest()[:16] + ".pdf")
    if not pricer_path.exists():
        print(f"ERROR: cached pricer PDF not found: {pricer_path}")
        return 1
    pages = pdf_pages(pricer_path)

    pilot_path = out_dir / "artcobell_supplier_pilot.csv"
    with pilot_path.open(newline="", encoding="utf-8") as fh:
        pilot_rows = list(csv.DictReader(fh))
    pilot_skus = {r["supplier_sku_model"] for r in pilot_rows}

    new_rows = build_rows(pages)
    overlap = pilot_skus & {r["supplier_sku_model"] for r in new_rows}
    if overlap:
        print(f"ERROR: new rows overlap pilot SKUs: {sorted(overlap)}")
        return 1

    new_rows = new_rows[:56]
    combined = pilot_rows + new_rows
    assert len(combined) == 100, f"expected 100 rows, got {len(combined)}"
    skus = [r["supplier_sku_model"] for r in combined]
    assert len(skus) == len(set(skus)), "duplicate SKUs in combined file"

    out_path = out_dir / "artcobell_supplier_100.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(combined)

    # --- Spot-check: re-locate each sampled model's price in pricer text --
    full_text = "\n".join(pages)
    spot = [new_rows[0], new_rows[20], new_rows[-1]]
    checks = []
    for r in spot:
        pat = re.compile(re.escape(r["supplier_sku_model"]) +
                         r".{0,220}?\$" +
                         re.escape(f"{int(r['list_price_usd']):,}"),
                         re.DOTALL)
        ok = bool(pat.search(full_text))
        checks.append((r["supplier_sku_model"], r["list_price_usd"], ok))

    # --- Summary -----------------------------------------------------------
    from collections import Counter
    cat_counts = Counter(r["supplier_category"] for r in new_rows)
    summary = [
        "# Artcobell expansion — summary",
        "",
        "Run date: 2026-11-10 (script: scrape_artcobell_expand.py)",
        f"Source: Artcobell List Pricer, Feb 15 2025 edition (public "
        f"procurement copy, cached PDF {pricer_path.name}).",
        "",
        "## Result",
        f"- Combined file: output/artcobell_supplier_100.csv — "
        f"{len(combined)} data rows (44 original pilot rows, unmodified, "
        f"+ {len(new_rows)} new rows).",
        "- Original pilot CSV (artcobell_supplier_pilot.csv) was not changed.",
        f"- Duplicate supplier_sku_model values in combined file: 0 "
        f"(verified; {len(skus)} unique SKUs).",
        "",
        "## New rows by category",
    ]
    for cat, n in sorted(cat_counts.items()):
        summary.append(f"- {cat}: {n}")
    summary += [
        "",
        "## Verification (spot-checks vs Pricer text)",
    ]
    for sku, price, ok in checks:
        summary.append(f"- {sku}: list ${int(price):,} — "
                       f"{'FOUND in pricer text at that price' if ok else 'NOT FOUND — CHECK'}")
    summary += [
        "",
        "## Conventions / caveats",
        "- Leg-kit rows keep the Pricer's Units-Per-Carton descriptor "
        "verbatim (\"4-Legs\" / \"2-Legs\" = legs per kit carton); caster "
        "packs show \"4-pack\", the felt glide pack \"100\".",
        "- Dimensions for leg kits are the Pricer's height (range for "
        "adjustable kits, fixed height from the description for fixed kits).",
        "- spec_source_url is blank for the accessory rows: no separate "
        "spec sheet for them exists in the pilot cache; they are sourced "
        "from the List Pricer (source_page_url).",
        "- dealer_cost_usd stays blank on every row — dealer terms are not "
        "published anywhere in the source documents.",
        "- List prices are from the Feb 15, 2025 Pricer and must be "
        "re-verified against the current official dealer pricer before "
        "quoting.",
        "- image_url stays blank for new rows (no per-model image reliably "
        "matched), same convention as the pilot.",
    ]
    (out_dir / "expansion_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8")

    print(f"new_rows={len(new_rows)} total={len(combined)} csv={out_path}")
    print("categories:", dict(cat_counts))
    print("spot_checks:", checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
