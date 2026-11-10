#!/usr/bin/env python3
"""
Artcobell supplier spreadsheet REBALANCE — Signature School Products.

Builds output/artcobell_supplier_100_products.csv = the original 44 pilot
rows (Shape Table Tops, verbatim) + 56 COMPLETE-PRODUCT rows mined from the
other chapters of the SAME source: the Artcobell List Pricer, February 15,
2025 edition (public procurement copy already in cache/).

Chapters mined for the 56 new rows (pricer printed page numbers):
  * SOFT SEATING    (pp.11-16)  — squares, rounds, arcs, benches, ottomans
  * SEATING         (pp.33-53)  — Alphabet / Discover / NXT MOV chairs+stools
  * STUDENT DESKS   (pp.59-78)  — fully welded desks, open-front desks,
                                  combo desks
  * TEACHER STATIONS(p.105)     — ARISE podium (single)
  * STORAGE         (pp.114-121)— mobile shelves, bookshelves

No leg kits or accessories are used. If any chapter parser under-delivers
against its quota, the shortfall is filled from a fallback pool of other
complete products parsed from the same chapters (never components).

Rules (same as pilot): nothing invented — every price/dimension/weight
comes from the Pricer text; dealer_cost_usd stays blank (dealer terms
unpublished); image_url stays blank. New rows use last_scraped_date
2026-11-10. The two existing CSVs are never modified.

Usage: python3 scrape_artcobell_products.py [--cache-dir cache] [--out-dir output]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

PRICER_PDF_URL = (
    "https://SRM.MAGIC.MS.GOV:443/SAP/EBP/DOCSERVER/"
    "ARTCOBELL%20PRICELIST%5F2025%20CONDENSED.PDF"
    "?PHIOGET&KPID=767FE80500261FE08AD6593EC47FC166"
    "&KPCLASS=BBP_P_DOC&SAP-CLIENT=100"
)
SUPPLIER = BRAND = "Artcobell"
SCRAPE_DATE = "2026-11-10"
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
IMAGE_NOTE = "image_url blank: no per-model image reliably matched."
SPEC_NOTE = ("spec_source_url blank: no separate spec sheet for this "
             "product in the source set; sourced from the List Pricer "
             "(source_page_url).")
Q = '["\u201d\ufffd]'  # quote chars as extracted by pdftotext


def pdf_pages(pdf_path: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, timeout=600, check=True)
    return out.stdout.decode("utf-8", errors="replace").split("\f")


def norm(s: str) -> str:
    """Normalize quote chars to straight quotes and collapse whitespace."""
    s = s.replace("\u201d", '"').replace("\u201c", '"').replace("\ufffd", '"')
    return " ".join(s.split())


def money(s: str) -> str:
    return s.replace(",", "")


def money_disp(s: str) -> str:
    return f"${int(s.replace(',', '')):,}"


# ---------------------------------------------------------------------------
# Row scaffolding
# ---------------------------------------------------------------------------

def base_row(model: str) -> dict:
    return {c: "" for c in CSV_COLUMNS} | {
        "supplier": SUPPLIER, "supplier_sku_model": model, "brand": BRAND,
        "dealer_cost_usd": "", "image_url": "", "spec_source_url": "",
        "source_page_url": PRICER_PDF_URL,
        "last_scraped_date": SCRAPE_DATE,
    }


def std_notes(cubes: str, *extra: str) -> str:
    parts = list(extra)
    if cubes:
        parts.append(f"Cubes each: {cubes}.")
    parts += [PRICE_NOTE, DEALER_NOTE, IMAGE_NOTE, SPEC_NOTE]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Generic page parser: model rows + subgroup headings + desc continuations
# ---------------------------------------------------------------------------

def parse_page(page: str, regex: re.Pattern,
               subgroups: tuple[str, ...] = ()) -> list[dict]:
    out: list[dict] = []
    group = ""
    for raw in page.splitlines():
        line = raw.strip()
        if line in subgroups:
            group = line
            continue
        if line in ("Seat Pad", "Two Colors") and out \
                and out[-1]["desc"].rstrip().endswith(","):
            out[-1]["desc"] = out[-1]["desc"].rstrip() + " " + line
            continue
        m = regex.match(raw)
        if m:
            d = m.groupdict()
            d["group"] = group
            out.append(d)
    return out


# --- Regexes per pricer layout ---------------------------------------------

SS_RE = re.compile(  # Soft seating: 3 fabric-grade prices + legs required
    rf"^\s*(?P<model>SSD?-[\w.]+)\s+(?P<desc>.+?)\s{{2,}}(?P<dims>.+?)\s+"
    rf"(?P<units>\d+)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    rf"\$(?P<g1>[\d,]+)\s+\$(?P<g2>[\d,]+)\s+\$(?P<g3>[\d,]+)\s+"
    rf"(?P<legs>\d+)\s*$")

SEAT_UNITS_RE = re.compile(  # Seating with Units Per Ctn column
    rf"^\s*(?P<model>[A-Z][\w.-]*\d[\w.-]*)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>[\d.]+{Q})\s+(?P<units>\d+)\s+(?P<cubes>[\d.]+)\s+"
    rf"(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

SEAT_NOUNITS_RE = re.compile(  # Seating without Units Per Ctn column
    rf"^\s*(?P<model>[A-Z][\w.-]*\d[\w.-]*)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>[\d.]+{Q})\s+(?P<cubes>[\d.]+)\s+"
    rf"(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

SEAT_TWOTONE_RE = re.compile(  # NXT MOV: list price + 2-tone price
    rf"^\s*(?P<model>[A-Z][\w.-]*\d[\w.-]*)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>[\d.]+{Q}(?:\s*-\s*[\d.]+{Q})?)\s+(?P<units>\d+)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)"
    rf"(?:\s+\$(?P<price2>[\d,]+))?\s*$")

WELDED_RE = re.compile(  # Fully welded stacking desks (p.59)
    rf"^\s*(?P<model>SW[\w]+)\s+(?P<size>\d+{Q}\s*x\s*\d+{Q})\s+"
    rf"(?P<top>.+?)\s{{2,}}(?P<height>\d+{Q})\s+(?P<units>\d+)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s+"
    rf"\$(?P<prem>[\d,]+)\s*$")

OPENFRONT_RE = re.compile(  # Open-front desks (p.71)
    rf"^\s*(?P<model>DA[\w]+)\s+(?P<size>\d+{Q}\s*x\s*\d+{Q})\s+"
    rf"(?P<top>.+?)\s{{2,}}(?P<height>[\d.]+{Q}\s*-\s*[\d.]+{Q})\s+"
    rf"(?P<units>\d+)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    rf"\$(?P<price>[\d,]+)\s+(?P<mb>\$[\d,]+|N/A)\s*$")

COMBO_RE = re.compile(  # Combo desks (p.78)
    rf"^\s*(?P<model>D\d[\w]*)\s+(?P<size>\d+{Q}\s*x\s*\d+{Q})\s+"
    rf"(?P<top>.+?)\s{{2,}}(?P<height>[\d.]+{Q})\s+(?P<units>\d+)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

PODIUM_RE = re.compile(  # ARISE podium, single (p.105)
    rf"^\s*(?P<model>ATPA1F)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<units>\d+)\s+(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+"
    rf"\$(?P<price>[\d,]+)\s+\$(?P<prem>[\d,]+)\s*$")

SHELF_RE = re.compile(  # Mobile shelves (p.114): no units column
    rf"^\s*(?P<model>A[SD]FVSC-[\w.]+)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<size>\d+{Q}h\s*x\s*\d+{Q}w\s*x\s*\d+{Q}d)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

BOOKSHELF_RE = re.compile(  # Bookshelves (p.120): no units column
    rf"^\s*(?P<model>A\d+MBC)\s+(?P<size>.+?{Q}d)\s{{2,}}"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)\s*$")

STOOL_RE = re.compile(  # Discover stools (p.53): model starts with a digit
    rf"^\s*(?P<model>\d[\w.-]*)\s+(?P<desc>.+?)\s{{2,}}"
    rf"(?P<height>[\d.]+{Q}(?:\s*-\s*[\d.]+{Q})?)\s+(?P<units>\d+)\s+"
    rf"(?P<cubes>[\d.]+)\s+(?P<lbs>[\d.]+)\s+\$(?P<price>[\d,]+)"
    rf"(?:\s+\$(?P<price2>[\d,]+))?\s*$")


# ---------------------------------------------------------------------------
# Row builders per chapter
# ---------------------------------------------------------------------------

def soft_seating_rows(pages: list[str]) -> list[dict]:
    plan = [  # (pdf page, category tail, cap, subgroup headings)
        (11, "Circles + Squares > Square", 4, ("Square", "Round Rocker")),
        (12, "Circles + Squares > Round", 2, ()),
        (13, "Circles + Squares > Arcs", 2, ()),
        (14, "Benches > Curved", 2, ()),
        (15, "Benches > 2-Step", 1, ()),
        (16, "Benches > Ottoman", 1, ()),
    ]
    selected, extras = [], []
    for pg, tail, cap, subgroups in plan:
        parsed = parse_page(pages[pg - 1], SS_RE, subgroups)
        built = []
        for d in parsed:
            if d["group"]:  # e.g. p.11 also holds the Round Rocker table
                tail = f"Circles + Squares > {d['group']}"
            desc = norm(d["desc"])
            name = (f"Soft Seating {desc}" if desc[0].isalpha()
                    else f"{desc} Soft Seating")
            r = base_row(d["model"])
            r.update({
                "product_name": name,
                "description": (
                    f"{desc} — upholstered soft seating; durable foam "
                    f"core with wood base; standard with nylon glides; "
                    f"ships fully cartoned. List price shown is Grade 1 "
                    f"fabric."),
                "supplier_category": f"Soft Seating > {tail}",
                "dimensions": norm(d["dims"]),
                "list_price_usd": money(d["g1"]),
                "units_per_carton": d["units"],
                "weight_lbs": d["lbs"],
                "notes": std_notes(
                    d["cubes"],
                    f"Fabric Grade 2 list {money_disp(d['g2'])}; "
                    f"Grade 3 list {money_disp(d['g3'])}.",
                    f"Legs required: {d['legs']} (3\" legs and casters "
                    f"available separately per Pricer rules; standard "
                    f"configuration is nylon glides)."),
            })
            built.append(r)
        selected += built[:cap]
        extras += built[cap:]
    return selected + extras  # extras act as fallback, in order


def seating_rows(pages: list[str]) -> tuple[list[dict], list[dict]]:
    selected, extras = [], []

    def chair(d, name, category, stack_note, units_missing=False,
              twotone=None):
        r = base_row(d["model"])
        desc = norm(d["desc"])
        extra = [stack_note]
        if twotone:
            extra.append(f"2-tone list price {money_disp(twotone)}.")
        if units_missing:
            extra.append("units_per_carton blank: the Pricer table for "
                         "this section has no units-per-carton column.")
        r.update({
            "product_name": name,
            "description": f"{desc} — {name.lower()}, "
                           f"{norm(d['height'])} seat height.",
            "supplier_category": category,
            "dimensions": norm(d["height"]),
            "list_price_usd": money(d["price"]),
            "units_per_carton": d.get("units", ""),
            "weight_lbs": d["lbs"],
            "notes": std_notes(d["cubes"], *extra),
        })
        return r

    # Alphabet Four Leg Chair (p.39) — cap 8
    parsed = parse_page(pages[38], SEAT_UNITS_RE, ("With Bookrack", "FLOT"))
    built = []
    for d in parsed:
        note = ("Stacks 4 high (FLOT chairs stack 5 high); order in "
                "multiples of 4 (full carton quantity) per Pricer rules.")
        if d["group"] == "With Bookrack":
            note = ("Chair with bookrack; does not stack; order in "
                    "multiples of 2 (full carton quantity) per "
                    "Pricer rules.")
        built.append(chair(d, "Alphabet Four Leg Chair",
                           "Seating > Alphabet > Four Leg Chair", note))
    selected += built[:8]
    extras += built[8:]

    # Discover Four Leg Stacking Chair (p.46, main table) — cap 7
    parsed = parse_page(pages[45], SEAT_NOUNITS_RE)
    built = [chair(d, "Discover Four Leg Stacking Chair",
                   "Seating > Discover > Four Leg Stacking Chair",
                   "Stacks 10 high; four-leg chairs ship without "
                   "cartons on truckloads per Pricer rules.",
                   units_missing=True)
             for d in parsed]
    selected += built[:7]
    extras += built[7:]

    # NXT MOV Four Leg Chair (p.33) — cap 2; stools (p.36) — cap 2
    for pg, name, cat, cap in (
            (33, "NXT MOV Four Leg Chair",
             "Seating > NXT MOV > Four Leg Chair", 2),
            (36, "NXT MOV Four Leg Stool",
             "Seating > NXT MOV > Four Leg Stool", 2)):
        parsed = parse_page(pages[pg - 1], SEAT_TWOTONE_RE)
        built = [chair(d, name, cat,
                       "Order in multiples of 4 (full carton quantity) "
                       "per Pricer rules.",
                       twotone=d.get("price2"))
                 for d in parsed]
        selected += built[:cap]
        extras += built[cap:]

    # Discover Four Leg Stool (p.53) — cap 2 (adjustable-height stools)
    parsed = parse_page(pages[52], STOOL_RE)
    built = []
    for d in parsed:
        r = chair(d, "Discover Four Leg Stool",
                  "Seating > Discover > Four Leg Stool",
                  "Ships fully cartoned; order in multiples of 4 "
                  "(full carton quantity) per Pricer rules.",
                  twotone=d.get("price2"))
        r["description"] = (f"{norm(d['desc'])} — adjustable-height "
                            f"four-leg stool, {norm(d['height'])} "
                            f"seat height range; 13.5\" diameter seat.")
        r["dimensions"] = norm(d["height"])
        built.append(r)
    selected += built[:2]
    extras += built[2:]
    return selected, extras


def desk_rows(pages: list[str]) -> tuple[list[dict], list[dict]]:
    selected, extras = [], []

    # Fully Welded Stacking Desks (p.59) — cap 6
    groups = ("Expanse", "Linc", "Beta Straight", "Rectangle Belly Cut",
              "Rectangle")
    parsed = parse_page(pages[58], WELDED_RE, groups)
    built = []
    for d in parsed:
        r = base_row(d["model"])
        r.update({
            "product_name": f"{d['group']} Fully Welded Stacking Desk",
            "description": (
                f"Fully welded stacking student desk — {norm(d['size'])} "
                f"top, {norm(d['top'])}; {norm(d['height'])} high; "
                f"fully welded heavy-duty frame; ships fully assembled, "
                f"stacks 4 high."),
            "supplier_category": "Student Desks > Fully Welded Stacking "
                                 "Desks",
            "dimensions": f"{norm(d['size'])} top, {norm(d['height'])} high",
            "list_price_usd": money(d["price"]),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                f"List price is Standard (laminate); Premium/"
                f"Markerboard list {money_disp(d['prem'])}.",
                "Must order in multiples of two (full carton "
                "quantity) per Pricer rules."),
        })
        built.append(r)
    selected += built[:6]
    extras += built[6:]

    # Open Front Desks (p.71) — cap 4
    parsed = parse_page(pages[70], OPENFRONT_RE,
                        ("Poly Book Box", "Jumbo Poly Book Box"))
    built = []
    for d in parsed:
        r = base_row(d["model"])
        mb = d["mb"]
        mb_note = (f"Premium/Markerboard list {mb}."
                   if mb.startswith("$")
                   else "Markerboard top not available (N/A) for this "
                        "model per Pricer.")
        r.update({
            "product_name": f"{d['group']} Open Front Desk",
            "description": (
                f"Open-front student desk with {d['group'].lower()} — "
                f"{norm(d['size'])} top, {norm(d['top'])}; adjustable "
                f"height {norm(d['height'])}."),
            "supplier_category": "Student Desks > Open Front Desks",
            "dimensions": f"{norm(d['size'])} top, "
                          f"{norm(d['height'])} high (adjustable)",
            "list_price_usd": money(d["price"]),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                f"List price is Standard (laminate). {mb_note}"),
        })
        built.append(r)
    selected += built[:4]
    extras += built[4:]

    # Combo Desks (p.78) — cap 4 (D700 chair-desk combos first)
    page = pages[77]
    parsed = parse_page(page, COMBO_RE)
    built = []
    for d in parsed:
        series = "D800 Sled Combo Desk" if d["model"].startswith("D85") \
            else "D700 Combo Desk"
        r = base_row(d["model"])
        r.update({
            "product_name": series,
            "description": (
                f"Chair-desk combo unit — {norm(d['size'])} top, "
                f"{norm(d['top'])}; {norm(d['height'])} seat height; "
                f"standard with fixed wire book rack (D800 sled series) "
                f"per Pricer rules." if series.startswith("D800") else
                f"Chair-desk combo unit — {norm(d['size'])} top, "
                f"{norm(d['top'])}; {norm(d['height'])} seat height."),
            "supplier_category": "Student Desks > Combo Desks",
            "dimensions": f"{norm(d['size'])} top, "
                          f"{norm(d['height'])} seat height",
            "list_price_usd": money(d["price"]),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                "Ships fully cartoned; order in multiples of 2 "
                "(full carton quantity) per Pricer rules."),
        })
        built.append(r)
    selected += built[:4]
    extras += built[4:]
    return selected, extras


def teacher_rows(pages: list[str]) -> list[dict]:
    parsed = parse_page(pages[104], PODIUM_RE)
    built = []
    for d in parsed:
        size = re.search(rf"\d+{Q}\s*x\s*\d+{Q}", d["desc"])
        r = base_row(d["model"])
        r.update({
            "product_name": "ARISE Podium (Single)",
            "description": (
                f"{norm(d['desc'])} — pneumatic height-adjustable "
                f"teacher podium; fully welded base with 50mm hard "
                f"wheel locking casters; ships KD, field assembly "
                f"required."),
            "supplier_category": "Teacher Stations > ARISE Podium",
            "dimensions": norm(size.group(0)) + " top" if size else "",
            "list_price_usd": money(d["price"]),
            "units_per_carton": d["units"],
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                f"List price is Standard (laminate); Premium/"
                f"Markerboard list {money_disp(d['prem'])}."),
        })
        built.append(r)
    return built[:1]


def storage_rows(pages: list[str]) -> tuple[list[dict], list[dict]]:
    selected, extras = [], []

    # Mobile Shelves (p.114) — prefer Titanium (.4) finishes, cap 4
    parsed = parse_page(pages[113], SHELF_RE)
    built = []
    for d in parsed:
        r = base_row(d["model"])
        sided = "Double-Sided" if "Double" in d["desc"] else "Single-Sided"
        r.update({
            "product_name": f"Curved Mobile Shelf ({sided})",
            "description": (
                f"{norm(d['desc'])} curved mobile shelf unit, "
                f"{norm(d['size'])}; standard with 75mm NXT MOV "
                f"locking casters and docking magnets; ships fully "
                f"cartoned on pallet."),
            "supplier_category": "Storage > Mobile Shelves",
            "dimensions": norm(d["size"]),
            "list_price_usd": money(d["price"]),
            "units_per_carton": "",
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                "units_per_carton blank: Pricer table for this "
                "section has no units-per-carton column (ships "
                "cartoned on pallet)."),
        })
        built.append(r)
    titanium = [r for r in built
                if r["supplier_sku_model"].endswith(".4")]
    others = [r for r in built
              if not r["supplier_sku_model"].endswith(".4")]
    selected += titanium[:4]
    extras += titanium[4:] + others

    # Bookshelves (p.120) — cap 4
    parsed = parse_page(pages[119], BOOKSHELF_RE)
    built = []
    for d in parsed:
        size = norm(d["size"])
        height = size.split("h")[0] + 'h"'
        r = base_row(d["model"])
        r.update({
            "product_name": f"Bookshelf — {height}",
            "description": (
                f"Laminate bookshelf, {size}; 1\" core, back panels "
                f"match shelving and case; ships fully cartoned on "
                f"pallet."),
            "supplier_category": "Storage > Bookshelves",
            "dimensions": size,
            "list_price_usd": money(d["price"]),
            "units_per_carton": "",
            "weight_lbs": d["lbs"],
            "notes": std_notes(
                d["cubes"],
                "units_per_carton blank: Pricer table for this "
                "section has no units-per-carton column (ships "
                "cartoned on pallet)."),
        })
        built.append(r)
    selected += built[:4]
    extras += built[4:]
    return selected, extras


# ---------------------------------------------------------------------------

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
    assert len(pilot_rows) == 44, f"pilot has {len(pilot_rows)} rows"

    ss = soft_seating_rows(pages)
    ss_sel, ss_extra = ss[:12], ss[12:]
    seat_sel, seat_extra = seating_rows(pages)
    desk_sel, desk_extra = desk_rows(pages)
    teach_sel = teacher_rows(pages)
    stor_sel, stor_extra = storage_rows(pages)

    selected = ss_sel + seat_sel + desk_sel + teach_sel + stor_sel
    fallback = ss_extra + seat_extra + desk_extra + stor_extra
    chapter_counts = {
        "Soft Seating": len(ss_sel), "Seating": len(seat_sel),
        "Student Desks": len(desk_sel), "Teacher Stations": len(teach_sel),
        "Storage": len(stor_sel),
    }
    # Fill any shortfall from the complete-product fallback pool
    used_fallback = 0
    if len(selected) < 56:
        need = 56 - len(selected)
        selected += fallback[:need]
        used_fallback = min(need, len(fallback))
    selected = selected[:56]

    overlap = pilot_skus & {r["supplier_sku_model"] for r in selected}
    if overlap:
        print(f"ERROR: new rows overlap pilot SKUs: {sorted(overlap)}")
        return 1
    if len(selected) != 56:
        print(f"ERROR: only {len(selected)} complete-product rows found; "
              f"cannot reach 56 without components")
        return 1

    combined = pilot_rows + selected
    skus = [r["supplier_sku_model"] for r in combined]
    assert len(combined) == 100, f"expected 100 rows, got {len(combined)}"
    assert len(skus) == len(set(skus)), "duplicate SKUs in combined file"
    assert all(r["list_price_usd"] for r in combined), "unpriced row found"

    out_path = out_dir / "artcobell_supplier_100_products.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(combined)

    # --- Spot-checks: re-locate sampled models' prices in pricer text ----
    full_text = "\n".join(pages)
    by_sku = {r["supplier_sku_model"]: r for r in selected}
    spot_skus = [s for s in ("SS-SQ14", "D10A", "SWEX29", "A1272MBC",
                             "ATPA1F", "MS4L18", "DA0DE")
                 if s in by_sku]
    checks = []
    for sku in spot_skus:
        r = by_sku[sku]
        pat = re.compile(re.escape(sku) + r".{0,260}?\$" +
                         re.escape(f"{int(r['list_price_usd']):,}"),
                         re.DOTALL)
        checks.append((sku, r["list_price_usd"], bool(pat.search(full_text))))

    # --- Summary -----------------------------------------------------------
    cat_counts = Counter(r["supplier_category"] for r in selected)
    summary = [
        "# Artcobell rebalance — complete products (summary)",
        "",
        "Run date: 2026-11-10 (script: scrape_artcobell_products.py)",
        f"Source: Artcobell List Pricer, Feb 15 2025 edition (public "
        f"procurement copy, cached PDF {pricer_path.name}).",
        "",
        "## Result",
        f"- File: output/artcobell_supplier_100_products.csv — "
        f"{len(combined)} data rows = 44 original pilot Shape Table Top "
        f"rows (unmodified) + {len(selected)} new COMPLETE-product rows.",
        "- Complete products vs components in the new 56: "
        f"{len(selected)} complete / 0 components (all leg kits and "
        f"accessories from the earlier expansion were dropped).",
        "- Whole-file composition: 44 table tops (pilot base) + "
        "56 complete products = 100 rows; 0 leg kits, 0 accessories.",
        f"- Fallback-pool rows used to fill quotas: {used_fallback}.",
        f"- Duplicate supplier_sku_model values: 0 "
        f"({len(skus)} unique SKUs); every row carries a list price.",
        "",
        "## New rows by chapter (quota selection)",
    ]
    for ch, n in chapter_counts.items():
        summary.append(f"- {ch}: {n}")
    summary += ["", "## New rows by category"]
    for cat, n in sorted(cat_counts.items()):
        summary.append(f"- {cat}: {n}")
    summary += ["", "## Verification (spot-checks vs Pricer text)"]
    for sku, price, ok in checks:
        summary.append(f"- {sku}: list ${int(price):,} — "
                       f"{'FOUND in pricer text at that price' if ok else 'NOT FOUND — CHECK'}")
    summary += [
        "",
        "## Chapters mined",
        "- Soft Seating (pricer pp.11-16): Circles + Squares (Square, "
        "Round, Arcs), Benches (Curved, 2-Step, 38\" Ottoman). List "
        "price recorded is Grade 1 fabric; Grade 2/3 list prices are "
        "recorded in each row's notes.",
        "- Seating (pricer pp.33-53): Alphabet Four Leg Chairs, Discover "
        "Four Leg Stacking Chairs, NXT MOV Four Leg Chairs and Stools, "
        "Discover Four Leg Stools. For Discover stacking chairs the "
        "Pricer table has no units-per-carton column (left blank, "
        "noted in-row).",
        "- Student Desks (pricer pp.59-78): Fully Welded Stacking "
        "Desks, Open Front Desks (poly/jumbo book box), Combo Desks. "
        "Standard laminate list price recorded; Premium/Markerboard "
        "list price recorded in notes where published.",
        "- Teacher Stations (pricer p.105): ARISE Podium, Single only "
        "(the Double podium is sold as separate tops/bases/columns — "
        "components — and was excluded).",
        "- Storage (pricer pp.114-121): Curved Mobile Shelves "
        "(Titanium finish), Bookshelves. These Pricer tables have no "
        "units-per-carton column (left blank, noted in-row).",
        "",
        "## Conventions / caveats",
        "- dealer_cost_usd stays blank on every row — dealer terms are "
        "not published anywhere in the source documents.",
        "- List prices are from the Feb 15, 2025 Pricer and must be "
        "re-verified against the current official dealer pricer before "
        "quoting.",
        "- image_url and spec_source_url stay blank for new rows (no "
        "per-model image or separate spec sheet reliably matched in "
        "the source set), consistent with the pilot convention.",
        "- Dimensions follow each Pricer table's own data: overall "
        "dimensions for soft seating and storage; seat height for "
        "chairs/stools/combos; top size + height for desks.",
        "- The earlier component-based file "
        "(artcobell_supplier_100.csv) and the pilot CSV were not "
        "modified.",
    ]
    (out_dir / "rebalance_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8")

    print(f"new_rows={len(selected)} total={len(combined)} csv={out_path}")
    print("chapters:", chapter_counts)
    print("categories:", dict(cat_counts))
    print("fallback_used:", used_fallback)
    print("spot_checks:", checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
