#!/usr/bin/env python3
"""
Offices To Go (officestogo.com) supplier scraper for Signature School Products.

Produces a supplier CSV in the exact column format of the Artcobell pilot:
supplier,supplier_sku_model,brand,product_name,description,supplier_category,
dimensions,list_price_usd,dealer_cost_usd,units_per_carton,weight_lbs,
image_url,spec_source_url,source_page_url,last_scraped_date,notes

Data sources (all public, no login):
- Category listings: https://www.officestogo.com/en-us/products/series/{category}
  Cards carry model, product name, image and the published "Starting at" list price.
  (Product detail pages do NOT render a price in their HTML, so the listing
  "Starting at" price is the published list price source.)
- Product detail pages: /en-us/products/model/{cat}/{series}/{MODEL}
  carry the feature description, overall dimensions and a spec (cut) sheet PDF.

Honesty rules (same as Artcobell pilot):
- dealer_cost_usd left blank: dealer terms are not published.
- Weight / units-per-carton are not published on product pages or cut sheets,
  so they are left blank, never estimated.
- Nothing is invented: unparseable fields stay blank.
"""
import csv
import hashlib
import html as html_mod
import os
import re
import sys
import time

import requests

BASE = "https://www.officestogo.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache")
OUT_CSV = os.path.join(HERE, "output", "officestogo_supplier.csv")
SCRAPE_DATE = "2026-11-10"
TARGET_MAX = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# (slug, group, display name) in the order shown on the supplier homepage/menu.
CATEGORIES = [
    ("mesh-work-task-seating", "Seating", "Mesh Work + Task Seating"),
    ("work-task-seating", "Seating", "Work + Task Seating"),
    ("conference-management-seating", "Seating", "Conference + Workspace Seating"),
    ("guest-seating", "Seating", "Guest Seating"),
    ("nesting-chairs", "Seating", "Nesting Chairs"),
    ("stack-seating", "Seating", "Stack Seating"),
    ("lounge-seating", "Seating", "Lounge Seating"),
    ("seating-accessories", "Seating", "Seating Accessories"),
    ("superior-laminate-desking", "Desking & Tables", "Laminate Desking + Tables"),
    ("height-adjustable-tables", "Desking & Tables", "Height Adjustable Tables"),
    ("flip-top-training-tables", "Desking & Tables", "Flip Top Training Tables"),
    ("conference-meeting-tables", "Desking & Tables", "Conference + Meeting Tables"),
    ("desking-accessories", "Desking & Tables", "Desking Accessories"),
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch(url, binary=False):
    """Fetch with a file cache and retries (site can be slow)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()
    ext = ".pdf" if url.lower().endswith(".pdf") else ".html"
    path = os.path.join(CACHE_DIR, key + ext)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8", "ignore")
    last_err = None
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=90)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
            time.sleep(0.4)
            return r.content if binary else r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_err}")


def clean_text(fragment):
    """Strip tags to readable text, keeping element boundaries as ' | '."""
    fragment = re.sub(r'<script.*?</script>', ' ', fragment, flags=re.S | re.I)
    fragment = re.sub(r'<style.*?</style>', ' ', fragment, flags=re.S | re.I)
    fragment = re.sub(r'</(div|li|p|h\d|tr)>', ' | ', fragment, flags=re.I)
    fragment = re.sub(r'<br\s*/?>', ' | ', fragment, flags=re.I)
    fragment = re.sub(r'<[^>]+>', ' ', fragment)
    fragment = html_mod.unescape(fragment)
    fragment = re.sub(r'\s+', ' ', fragment)
    fragment = re.sub(r'(\s*\|\s*)+', ' | ', fragment)
    return fragment.strip(' |').strip()


def parse_cards(listing_html, listing_url):
    """Extract product cards from a category listing page."""
    cards = []
    for m in re.finditer(
        r'<a class="products__item" href="(?P<url>https://www\.officestogo\.com/en-us/products/model/[^"]+)">(?P<body>.*?)</a>',
        listing_html, re.S,
    ):
        body = m.group("body")
        url = m.group("url")
        model_m = re.search(r'products__item-title">([^<]+)<', body)
        model = model_m.group(1).strip() if model_m else url.rstrip("/").split("/")[-1]
        # Name: the plain <div> right after the title div
        name = ""
        name_m = re.search(r'products__item-title">[^<]+</div>\s*<div>([^<]+)</div>', body)
        if name_m:
            name = html_mod.unescape(name_m.group(1)).strip()
        price = ""
        price_m = re.search(r'Starting at\s*\$([\d,]+\.\d{2})', clean_text(body))
        if price_m:
            price = price_m.group(1)
        img_m = re.search(r'<img src="(https://files\.officestogo\.com/pictures/[^"]+)"', body)
        image = img_m.group(1) if img_m else ""
        series = url.split("/")[-2]
        cards.append({
            "model": model, "name": name, "price": price, "image": image,
            "detail_url": url, "series": series, "listing_url": listing_url,
        })
    return cards


def parse_detail(detail_html, model, name=""):
    """Pull description, dimensions, main image and spec sheet from a detail page."""
    text = clean_text(detail_html)

    desc = ""
    # Feature text sits between the Downloads block and the Dimensions block.
    seg_m = re.search(r'Images \(ZIP\)(.*?)Dimensions', text, re.S)
    if seg_m:
        seg = seg_m.group(1).strip(' |').strip()
        # Segment is "{MODEL} | {Name} | Feature | Feature ..." — drop the
        # first one or two lead-in tokens naming the model/product.
        parts = [p.strip() for p in seg.split(' | ') if p.strip()]
        if parts and parts[0] == model:
            parts = parts[1:]
            if parts and name and parts[0].lower() == name.lower():
                parts = parts[1:]
        desc = ' | '.join(parts)
    if not desc:
        # Fallback: everything between the second name heading and 'Dimensions'
        seg_m = re.search(r'Downloads(.*?)Dimensions', text, re.S)
        if seg_m:
            desc = re.sub(r'^.*?Images \(ZIP\)\s*', '', seg_m.group(1), flags=re.S).strip()

    dims = ""
    dim_m = re.search(
        r'Dimensions\s*\|?\s*((?:[\d.]+["\u201d][a-zA-Z]\s*x\s*){1,2}[\d.]+["\u201d][a-zA-Z])',
        text)
    if dim_m:
        raw = dim_m.group(1).replace('\u201d', '"')
        parts = re.findall(r'([\d.]+)"([a-zA-Z])', raw)
        dims = " x ".join(f'{v}"{u.upper()}' for v, u in parts)

    # Spec sheet PDF: prefer the *_Cut_Sheet_*.pdf for this model
    spec = ""
    pdfs = re.findall(r'href="(https://files\.officestogo\.com/files/[^"]+\.pdf)"', detail_html)
    for p in pdfs:
        if model in p and "Cut_Sheet" in p:
            spec = p
            break
    if not spec:
        # Anchor labelled "Product Spec Sheet" in the Downloads block
        dl_m = re.search(r'Product Spec Sheet:\s*<a[^>]+href="([^"]+)"', detail_html)
        if not dl_m:
            dl_m = re.search(r'<a[^>]+href="(https://files\.officestogo\.com/files/[^"]*(?:Spec|Cut)[^"]*\.pdf)"', detail_html)
        if dl_m:
            spec = dl_m.group(1)

    # Main product image: a pictures/ file containing the model, Front view, not a thumb
    image = ""
    imgs = re.findall(r'https://files\.officestogo\.com/pictures/[^"\')\s]+', detail_html)
    front = [i for i in imgs if model in i and "Front" in i and "thumb" not in i]
    if front:
        image = front[0]
    else:
        any_model = [i for i in imgs if model in i and "thumb" not in i]
        if any_model:
            image = any_model[0]
    return desc, dims, spec, image


def fmt_price(raw):
    """Normalize '1,157.00' -> '1157'; keep cents when not .00."""
    if not raw:
        return ""
    raw = raw.replace(",", "")
    if raw.endswith(".00"):
        return raw[:-3]
    return raw


def main():
    all_cards = {}  # model -> card (first seen wins)
    order = []
    for slug, group, display in CATEGORIES:
        listing_url = f"{BASE}/en-us/products/series/{slug}"
        try:
            listing_html = fetch(listing_url)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: listing failed {listing_url}: {e}", file=sys.stderr)
            continue
        cards = parse_cards(listing_html, listing_url)
        # Also follow any /products/models/ series listings linked from the page
        extra = sorted(set(re.findall(
            r'href="(https://www\.officestogo\.com/en-us/products/models/[^"]+)"', listing_html)))
        for extra_url in extra:
            try:
                cards += parse_cards(fetch(extra_url), extra_url)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: extra listing failed {extra_url}: {e}", file=sys.stderr)
        print(f"{display}: {len(cards)} cards")
        for c in cards:
            c["group"] = group
            c["display"] = display
            c["cat_slug"] = slug
            if c["model"] not in all_cards:
                all_cards[c["model"]] = c
                order.append(c["model"])

    print(f"Total distinct models found: {len(order)}")
    selected = order[:TARGET_MAX]
    if len(order) > TARGET_MAX:
        print(f"Capping at {TARGET_MAX} rows (seating categories first, then desking).")

    rows = []
    for i, model in enumerate(selected, 1):
        c = all_cards[model]
        desc = dims = spec = ""
        image = c["image"]
        try:
            detail_html = fetch(c["detail_url"])
            d_desc, d_dims, d_spec, d_image = parse_detail(detail_html, model, c["name"])
            desc, dims, spec = d_desc, d_dims, d_spec
            if d_image:
                image = d_image
        except Exception as e:  # noqa: BLE001
            print(f"WARN: detail failed {model}: {e}", file=sys.stderr)
        category = f'{c["group"]} > {c["display"]}'
        series = c["series"]
        if series and series != f"{c['cat_slug']}-series" and not series.endswith("-series"):
            pretty = series.replace("-", " ").title()
            category = f"{category} > {pretty}"
        notes = (
            'List price is the published "Starting at" (base configuration) list price '
            "shown on the supplier category listing at officestogo.com; product detail "
            "pages do not render a price in HTML. dealer_cost_usd blank: dealer terms "
            "not published. Weight and units_per_carton not published on the product "
            "page or its cut sheet, so left blank."
        )
        if not c["price"]:
            notes = ("Price not published on supplier site — quote only / verify with "
                     "supplier. " + notes)
        rows.append({
            "supplier": "Offices To Go",
            "supplier_sku_model": model,
            "brand": "Offices To Go",
            "product_name": c["name"],
            "description": desc,
            "supplier_category": category,
            "dimensions": dims,
            "list_price_usd": fmt_price(c["price"]),
            "dealer_cost_usd": "",
            "units_per_carton": "",
            "weight_lbs": "",
            "image_url": image,
            "spec_source_url": spec,
            "source_page_url": c["listing_url"],
            "last_scraped_date": SCRAPE_DATE,
            "notes": notes,
        })
        if i % 10 == 0:
            print(f"  detailed {i}/{len(selected)}")

    fields = ["supplier", "supplier_sku_model", "brand", "product_name", "description",
              "supplier_category", "dimensions", "list_price_usd", "dealer_cost_usd",
              "units_per_carton", "weight_lbs", "image_url", "spec_source_url",
              "source_page_url", "last_scraped_date", "notes"]
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT_CSV}")


if __name__ == "__main__":
    main()
