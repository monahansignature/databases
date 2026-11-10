#!/usr/bin/env python3
"""
Scrape the Made by Marco (Marco) public catalog into the Signature School
Products supplier spreadsheet format.

Source: https://madebymarco.net/ — a WordPress + WooCommerce site.
Data comes from the site's public WooCommerce Store API
(/wp-json/wc/store/v1/products), which is the same data the storefront
renders. No login is used and no data is invented:

- The site publishes NO prices (every product's price is 0 / empty in the
  API), so list_price_usd is left blank and every row is noted
  "Price not published on supplier site".
- dealer_cost_usd is always blank: dealer terms are not published.
- Dimensions/weight are only filled from reliable matches: the store's
  structured data when expressed in inches / lbs (rare — on the run date
  only 2 of 270 products had any, and those were implausible metric
  placeholder values), or the Model/Description/Dimensions spec table
  embedded in the product page itself, matched on the exact model number.
- Some product pages list several model numbers in a single SKU field
  (separated by ',' or ';'). Following the one-row-per-model convention of
  the Artcobell pilot, each model number becomes its own row.
- Selection: the full catalog has more models than the TARGET below, so rows
  are picked round-robin across top-level categories (each category sorted
  by product name, then model) to keep a representative spread.

Output: output/madebymarco_supplier.csv with the exact Artcobell pilot
columns. Re-running re-fetches live data.
"""

import csv
import html
import os
import re
import sys

import requests

BASE = "https://madebymarco.net"
STORE_API = BASE + "/wp-json/wc/store/v1"
SPEC_INDEX_URL = BASE + "/spec-sheets-2/"
SUPPLIER = "Made by Marco"
BRAND = "Marco"  # brand name the site itself uses (site title / copyright)
SCRAPE_DATE = "2026-11-10"
TARGET_ROWS = 100
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

COLUMNS = [
    "supplier", "supplier_sku_model", "brand", "product_name", "description",
    "supplier_category", "dimensions", "list_price_usd", "dealer_cost_usd",
    "units_per_carton", "weight_lbs", "image_url", "spec_source_url",
    "source_page_url", "last_scraped_date", "notes",
]

# Keyword rules (checked in order) mapping a product to the spec-sheet PDF
# the supplier publishes for its line, from https://madebymarco.net/spec-sheets-2/
UP = BASE + "/wp-content/uploads/"
SPEC_PDF_RULES = [
    (r"bandstor|\bBS\d{3}\b|folio|conductor|percussion|cymbal|guitar rack",
     UP + "2025/09/Bandstor-Spec-Sheets-1.pdf"),
    (r"mg2200|MG-22|kidney activity|horseshoe activity|flower activity|clover activity",
     UP + "2025/11/MG2200_Tables-specs.pdf"),
    (r"apex.*seat|apex.*chair|apex.*stool|\b381\d\d\b|\b382\d\d\b|apex cantilever|apex stacking",
     UP + "2025/11/Apex_Seating-specs.pdf"),
    (r"apex.*table|apex.*desk|apex.*student",
     UP + "2025/09/Apex_Tables-specs.pdf"),
    (r"premier.*desk",
     UP + "2025/11/Premier_Desks-specs-NEW.pdf"),
    (r"premier",
     UP + "2025/09/Premier_Tables-specs-NEW.pdf"),
    (r"sonik",
     UP + "2025/09/Sonik_soft_seating-specs.pdf"),
    (r"horizon",
     UP + "2025/09/Horizon-Spec-Sheets.pdf"),
    (r"bookcase",
     UP + "2025/11/Bookcases-specsheets.pdf"),
    (r"cubbie",
     UP + "2025/11/Cubbie-Storage-specsheet.pdf"),
    (r"floor table|floor rectangle",
     UP + "2025/09/Floor_Tables-specs.pdf"),
    (r"swivel stool",
     UP + "2025/11/Cushioned-Swivel-Stool-specs.pdf"),
    (r"mg1100",
     UP + "2025/11/MG1100-Seating-specs-1.pdf"),
    (r"mobile casegood",
     UP + "2025/11/Mobile-Casegoods-specs.pdf"),
    (r"multimedia",
     UP + "2025/11/Multimedia-Tables-specs.pdf"),
    (r"cafe table",
     UP + "2025/11/Cafe_Tables-specs.pdf"),
    (r"meeting table",
     UP + "2025/09/Meeting-Tables-Spec-Sheet.pdf"),
    (r"instructor|lectern",
     UP + "2025/09/Instructor-Stations-spec-sheets.pdf"),
    (r"circulation",
     UP + "2025/09/Circulation-Desk-Spec-Sheets.pdf"),
    (r"room divider",
     UP + "2025/10/Room-Dividers-Spec-Sheet.pdf"),
    (r"cushion cadd",
     UP + "2025/10/Cushion-Caddies-specs.pdf"),
    (r"summit",
     UP + "2025/10/Summit-Cart-specs-1.pdf"),
    (r"t-leg|t leg",
     UP + "2025/10/T-Leg-Desks-specsheets.pdf"),
    (r"flip|nest|training table",
     UP + "2025/09/Flip-and-Nest-Training-Tables-spec.pdf"),
]


def get_json(session, url, params=None, attempts=4):
    last_err = None
    for i in range(attempts):
        try:
            r = session.get(url, params=params, headers=UA, timeout=120)
            r.raise_for_status()
            return r, r.json()
        except requests.RequestException as e:  # site can be slow; retry
            last_err = e
            if i < attempts - 1:
                import time
                time.sleep(5 * (i + 1))
    raise last_err


def fetch_all_products(session):
    products, page = [], 1
    while True:
        r, data = get_json(session, STORE_API + "/products",
                           {"per_page": 50, "page": page})
        products.extend(data)
        total_pages = int(r.headers.get("X-WP-TotalPages", page))
        if page >= total_pages:
            return products
        page += 1


def fetch_category_paths(session):
    """Return {category_id: 'Top > Sub > Leaf'} using the categories endpoint."""
    _, cats = get_json(session, STORE_API + "/products/categories",
                       {"per_page": 100})
    by_id = {c["id"]: c for c in cats}

    def path(cat_id, seen=None):
        seen = seen or set()
        parts, cur = [], cat_id
        while cur and cur in by_id and cur not in seen:
            seen.add(cur)
            c = by_id[cur]
            parts.append(html.unescape(c["name"]).strip())
            cur = c.get("parent") or 0
        return " > ".join(reversed(parts))

    return {cid: path(cid) for cid in by_id}


def clean_text(raw, limit=500):
    if not raw:
        return ""
    t = re.sub(r"<[^>]+>", " ", raw)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[: limit - 3].rsplit(" ", 1)[0] + "..."
    return t


def split_models(sku_field):
    if not sku_field:
        return []
    parts = [p.strip() for p in re.split(r"[,;]", sku_field)]
    return [p for p in parts if p]


def spec_url_for(product_name, category_path):
    hay = (product_name + " " + category_path).lower()
    for pattern, url in SPEC_PDF_RULES:
        if re.search(pattern, hay, re.I):
            return url
    return SPEC_INDEX_URL


def dims_and_weight(product):
    """Only trust structured dims/weight expressed in inches / lbs."""
    dims = ""
    fd = (product.get("formatted_dimensions") or "").strip()
    if fd and fd.upper() != "N/A" and "cm" not in fd.lower():
        dims = fd.replace("×", "x")
    weight = ""
    fw = (product.get("formatted_weight") or "").strip()
    m = re.match(r"^([\d.]+)\s*(lbs?|pounds?)$", fw, re.I)
    if m:
        weight = m.group(1)
    return dims, weight


def parse_model_dims(page_html):
    """Extract {MODEL: (dimensions, weight)} from the spec tables embedded
    in a product page (JSON 'tables' payloads with Model/Dimensions
    columns). Only exact model-number matches are returned."""
    import json as _json
    found = {}
    # The payload is HTML-entity-encoded JSON inside the page; unescape first,
    # then pull each string literal out of the "tables":[...] arrays.
    text = html.unescape(page_html)
    tables = []
    for m in re.finditer(r'"tables"\s*:\s*\[', text):
        i = m.end()
        while i < len(text) and text[i] != "]":
            if text[i] == '"':
                j = i + 1
                while j < len(text):
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == '"':
                        break
                    j += 1
                try:
                    tables.append(_json.loads(text[i:j + 1]))
                except Exception:
                    pass
                i = j + 1
            else:
                i += 1
    for tbl in tables:
        if not isinstance(tbl, str):
            continue
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S | re.I):
            cells = [clean_text(c, 200) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if cells:
                rows.append(cells)
        if not rows:
            continue
        header = [c.lower() for c in rows[0]]
        mi = next((i for i, c in enumerate(header) if "model" in c), None)
        di = next((i for i, c in enumerate(header) if "dimension" in c), None)
        wi = next((i for i, c in enumerate(header) if "weight" in c), None)
        if mi is None or di is None:
            continue
        for cells in rows[1:]:
            if len(cells) <= max(mi, di):
                continue
            model = cells[mi].strip().upper()
            dims = cells[di].replace("^", '"').strip()
            dims = dims.replace("u201d", '"').replace("u201c", '"')
            dims = dims.replace("u2013", "–").replace("u2014", "—")
            dims = re.sub(r"\s+", " ", dims)
            weight = ""
            if wi is not None and len(cells) > wi:
                wv = cells[wi].strip()
                if re.fullmatch(r"[\d.]+", wv) or re.search(r"\blbs?\b", wv, re.I):
                    weight = re.sub(r"[^\d.]", "", wv)
            if model and dims:
                found.setdefault(model, (dims, weight))
    return found


def enrich_from_product_pages(session, picked):
    """Fetch each selected product's page once and fill dimensions/weight
    from its embedded spec table where the model number matches exactly."""
    by_url = {}
    for r in picked:
        by_url.setdefault(r["source_page_url"], []).append(r)
    filled = 0
    for url, rows in by_url.items():
        try:
            resp = session.get(url, headers=UA, timeout=120)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        table = parse_model_dims(resp.text)
        for r in rows:
            sku = r["supplier_sku_model"].upper()
            hit = table.get(sku)
            if not hit:
                # Site spec tables sometimes list the base model plus
                # option-code slots, e.g. "38-2265-XX-XXX" for SKU 38-2265.
                # Only accept the match when the extra suffix is pure X slots.
                for key, val in table.items():
                    base = re.sub(r"(-X+)+$", "", key)
                    if base == sku and base != key:
                        hit = val
                        break
            if hit:
                dims, weight = hit
                if dims and not r["dimensions"]:
                    r["dimensions"] = dims
                    filled += 1
                    r["notes"] += (" Dimensions from spec table on supplier "
                                   "product page (model-number match).")
                if weight and not r["weight_lbs"]:
                    r["weight_lbs"] = weight
    return filled


def build_rows(products, cat_paths):
    """One row per model number; returns (rows, stats)."""
    rows, seen_models, dupes = [], {}, []
    for p in products:
        models = split_models(p.get("sku"))
        if not models:
            continue
        name = html.unescape(p["name"]).strip()
        desc = clean_text(p.get("short_description")) or clean_text(p.get("description"))
        # Most specific (deepest) category path wins; ties -> first listed.
        paths = [cat_paths.get(c["id"], html.unescape(c["name"]))
                 for c in p.get("categories", [])]
        category = max(paths, key=lambda s: s.count(">")) if paths else ""
        top_cat = category.split(" > ")[0] if category else "Uncategorized"
        dims, weight = dims_and_weight(p)
        price_cents = int(p["prices"].get("regular_price") or 0)
        price = f"{price_cents / 100:.2f}".rstrip("0").rstrip(".") if price_cents > 0 else ""
        image = p["images"][0]["src"] if p.get("images") else ""
        spec_url = spec_url_for(name, category)
        attr_names = [a["name"] for a in p.get("attributes", [])]
        for model in models:
            key = model.upper()
            if key in seen_models:
                dupes.append(model)
                continue
            seen_models[key] = p["id"]
            notes = ["Price not published on supplier site — quote only / "
                     "verify with supplier.",
                     "dealer_cost_usd blank: dealer terms not published."]
            if len(models) > 1:
                notes.append(f"Product page lists {len(models)} models "
                             f"({'; '.join(models)}); this row is model {model}.")
            if p["type"] == "variable":
                notes.append("Variable product: options configured on product "
                             "page; no per-variation SKUs published.")
            if attr_names:
                notes.append("Options on product page: " +
                             ", ".join(attr_names) + ".")
            rows.append({
                "supplier": SUPPLIER,
                "supplier_sku_model": model,
                "brand": BRAND,
                "product_name": name,
                "description": desc,
                "supplier_category": category,
                "dimensions": dims,
                "list_price_usd": price,
                "dealer_cost_usd": "",
                "units_per_carton": "",
                "weight_lbs": weight,
                "image_url": image,
                "spec_source_url": spec_url,
                "source_page_url": p["permalink"],
                "last_scraped_date": SCRAPE_DATE,
                "notes": " ".join(notes),
                "_top_cat": top_cat,
            })
    return rows, {"dupes_dropped": dupes}


def select_spread(rows, target):
    """Round-robin across top-level categories for a representative spread."""
    groups = {}
    for r in rows:
        groups.setdefault(r["_top_cat"], []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: (r["product_name"].lower(), r["supplier_sku_model"]))
    order = sorted(groups)
    picked, idx = [], {k: 0 for k in order}
    while len(picked) < target:
        progressed = False
        for k in order:
            if idx[k] < len(groups[k]):
                picked.append(groups[k][idx[k]])
                idx[k] += 1
                progressed = True
                if len(picked) >= target:
                    break
        if not progressed:
            break
    return picked


def main():
    session = requests.Session()
    products = fetch_all_products(session)
    cat_paths = fetch_category_paths(session)
    rows, stats = build_rows(products, cat_paths)
    picked = select_spread(rows, TARGET_ROWS)
    filled = enrich_from_product_pages(session, picked)
    print(f"dimensions filled from product-page spec tables: {filled}")
    for r in picked:
        r.pop("_top_cat", None)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "madebymarco_supplier.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(picked)
    print(f"products in API: {len(products)}")
    print(f"products with SKU field: "
          f"{sum(1 for p in products if (p.get('sku') or '').strip())}")
    print(f"distinct model rows available: {len(rows)} "
          f"(dupes dropped: {len(stats['dupes_dropped'])})")
    print(f"rows written: {len(picked)} -> {out_path}")
    priced = sum(1 for p in products
                 if int(p['prices'].get('regular_price') or 0) > 0)
    print(f"products with a published price: {priced}")


if __name__ == "__main__":
    sys.exit(main())
