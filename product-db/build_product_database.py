#!/usr/bin/env python3
"""Build the Signature School Products customer-facing product database (layer 2)
from the master supplier spreadsheet (layer 1, single source of truth).

Draft v1 mapping rules are documented in product_database_notes.md.
Re-runnable: python3 build_product_database.py
"""
import csv, re, html, os, sys

MASTER = os.path.expanduser('~/workspace/goals/signature-school-products-quote-first-catalog/files/supplier_spreadsheet_master.csv')
OUT    = os.path.expanduser('~/workspace/goals/signature-school-products-quote-first-catalog/files/product_database_draft.csv')
TODAY  = '2026-11-10'

PREFIX = {'Artcobell': 'ART', 'Made by Marco': 'MAR', 'Offices To Go': 'OTG'}

def clean_desc(text, limit=320):
    if not text:
        return ''
    t = html.unescape(text)
    t = re.sub(r'<[^>]+>', ' ', t)                 # strip HTML (WooCommerce descriptions)
    t = re.sub(r'\s+', ' ', t).strip()
    # drop obvious internal/spec-only lead-ins for Artcobell-style spec strings is kept (draft)
    if len(t) > limit:
        t = t[:limit].rsplit(' ', 1)[0].rstrip(' ,;') + '…'
    return t

def slugify(text):
    s = text.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return re.sub(r'-{2,}', '-', s)

def map_artcobell(cat, name):
    # returns (category, subcategory, rooms, grades)
    if cat.startswith('Tables > Shape Table Tops'):
        return ('Tables', 'Activity Tables — Shape Tops', 'Classroom; Early Learning; Library & Media Center', 'Early Learning (PreK–K); Elementary; Middle School')
    if cat.startswith('Seating >'):
        sub = 'Stools' if 'Stool' in cat else 'Chairs'
        return ('Seating', sub, 'Classroom', 'Elementary; Middle School')
    if cat.startswith('Soft Seating'):
        sub = 'Ottomans & Benches' if ('Ottoman' in cat or 'Benches' in cat) else 'Modular Soft Seating'
        return ('Soft Seating', sub, 'Classroom; Library & Media Center; Lounge & Commons', 'Early Learning (PreK–K); Elementary')
    if cat.startswith('Student Desks'):
        grades = 'Middle School; High School' if 'Combo' in cat else 'Elementary; Middle School'
        return ('Desks', 'Student Desks', 'Classroom', grades)
    if cat.startswith('Teacher Stations'):
        return ('Teacher & Staff', 'Podiums & Teacher Stations', 'Classroom', 'Staff / Adult')
    if cat.startswith('Storage'):
        return ('Storage', 'Shelving & Bookcases', 'Classroom; Library & Media Center', 'All Grades')
    return ('Classroom Furniture', cat, 'Classroom', 'All Grades')

def map_marco(cat, name):
    n = name.lower()
    if cat.startswith('Bandstor'):
        return ('Storage', 'Instrument Storage', 'Music Room; Classroom', 'Middle School; High School')
    if cat.startswith('Sonik'):
        return ('Soft Seating', 'Ottomans & Benches', 'Classroom; Library & Media Center; Lounge & Commons', 'Early Learning (PreK–K); Elementary; Middle School')
    if cat.startswith('Aquarium Stands'):
        return ('Science & STEM', 'Aquarium Stands', 'Science Lab; Classroom', 'Elementary; Middle School; High School')
    if 'Apex™ Tables' in cat:
        return ('Tables', 'Activity & Student Tables', 'Classroom', 'Elementary; Middle School')
    if 'Collaborative Desks' in cat:
        return ('Desks', 'Student Desks', 'Classroom', 'Elementary; Middle School')
    if cat.startswith('Storage & Organization'):
        if 'Cubbie' in cat:
            return ('Storage', 'Cubby Storage', 'Classroom; Early Learning', 'Early Learning (PreK–K); Elementary')
        if 'Makerspace' in cat:
            return ('Makerspace', 'Makerspace Storage & Workstations', 'Makerspace / STEM Lab; Classroom', 'Elementary; Middle School; High School')
        return ('Storage', 'Mobile Storage & Casegoods', 'Classroom; Library & Media Center', 'All Grades')
    if cat.startswith('Library'):
        if 'Circulation' in cat:
            return ('Library & Media', 'Circulation Desks', 'Library & Media Center', 'Staff / Adult')
        return ('Library & Media', 'Bookcases', 'Library & Media Center', 'All Grades')
    if cat.startswith('Seating & Lounge'):
        return ('Seating', 'Chairs', 'Classroom; Lounge & Commons', 'Elementary; Middle School; High School')
    if cat.startswith('Accessories'):
        return ('Accessories', 'Desk Accessories', 'Classroom', 'All Grades')
    if cat.startswith('Quick Ship'):
        if 'chair' in n or 'seat' in n or 'stool' in n:
            return ('Seating', 'Chairs', 'Classroom', 'Elementary; Middle School')
        if 'table' in n or 'desk' in n:
            return ('Tables', 'Activity & Student Tables', 'Classroom', 'Elementary; Middle School')
        return ('Classroom Furniture', 'Quick Ship', 'Classroom', 'All Grades')
    return ('Classroom Furniture', cat, 'Classroom', 'All Grades')

def map_otg(cat, name):
    if 'Mesh Work + Task' in cat or 'Work + Task' in cat:
        return ('Seating', 'Task Chairs', 'Office; Classroom', 'Staff / Adult')
    if 'Conference' in cat:
        return ('Seating', 'Conference Chairs', 'Office; Conference Room', 'Staff / Adult')
    if 'Guest' in cat:
        return ('Seating', 'Guest Chairs', 'Office; Reception & Waiting', 'Staff / Adult')
    if 'Lounge' in cat:
        return ('Seating', 'Lounge Chairs', 'Lounge & Commons; Library & Media Center', 'Middle School; High School; Staff / Adult')
    if 'Stack' in cat:
        return ('Seating', 'Stacking Chairs', 'Cafeteria; Classroom; Multi-Purpose Room', 'Elementary; Middle School; High School')
    if 'Nesting' in cat:
        return ('Seating', 'Nesting Chairs', 'Classroom; Multi-Purpose Room', 'Middle School; High School; Staff / Adult')
    if 'Accessories' in cat:
        return ('Accessories', 'Seating Accessories', 'Office; Classroom', 'Staff / Adult')
    if cat.startswith('Desking'):
        return ('Desks', 'Laminate Desks & Workstations', 'Office; Classroom', 'Staff / Adult')
    return ('Office Furniture', cat, 'Office', 'Staff / Adult')

MAPPERS = {'Artcobell': map_artcobell, 'Made by Marco': map_marco, 'Offices To Go': map_otg}

rows = list(csv.DictReader(open(MASTER)))
counters = {}
out_rows = []
used_slugs = set()
for r in rows:
    sup = r['supplier']
    counters[sup] = counters.get(sup, 0) + 1
    ssp_sku = f"SSP-{PREFIX[sup]}-{counters[sup]:04d}"
    category, subcat, rooms, grades = MAPPERS[sup](r['supplier_category'], r['product_name'])
    name = r['product_name'].strip()
    sku = r['supplier_sku_model'].strip()
    title = name if sku.lower() in name.lower() else f"{name} ({sku})"
    slug = slugify(f"{r['brand']} {name} {sku}")
    if slug in used_slugs:
        slug = slug + '-' + str(counters[sup])
    used_slugs.add(slug)
    list_price = r['list_price_usd'].strip()
    if list_price:
        ssp_price = list_price
        basis = 'Supplier list price — placeholder, pending pricing rule from Zachary'
    else:
        ssp_price = ''
        basis = 'No public supplier price — quote only until dealer price list is merged'
    publish, reason = 'yes', ''
    if not r['image_url'].strip():
        publish, reason = 'no', 'Missing product image — source from supplier media before publishing'
    elif not r['description'].strip():
        publish, reason = 'no', 'Missing product description'
    out_rows.append({
        'ssp_sku': ssp_sku,
        'supplier': sup,
        'supplier_sku_model': sku,
        'brand': r['brand'],
        'title': title,
        'category': category,
        'subcategory': subcat,
        'room_tags': rooms,
        'grade_levels': grades,
        'short_description': clean_desc(r['description']),
        'dimensions': r['dimensions'],
        'image_url': r['image_url'],
        'supplier_list_price_usd': list_price,
        'ssp_price_usd': ssp_price,
        'price_basis': basis,
        'show_price': 'no',
        'quote_only': 'yes',
        'publish': publish,
        'publish_reason': reason,
        'website_slug': slug,
        'spec_sheet_url': r['spec_source_url'],
        'last_updated': TODAY,
    })

fields = list(out_rows[0].keys())
with open(OUT, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(out_rows)

from collections import Counter
print('rows:', len(out_rows))
print('by supplier:', dict(Counter(r['supplier'] for r in out_rows)))
print('by category:', dict(Counter(r['category'] for r in out_rows)))
print('publish yes:', sum(1 for r in out_rows if r['publish']=='yes'), '| no:', sum(1 for r in out_rows if r['publish']=='no'))
print('priced (ssp):', sum(1 for r in out_rows if r['ssp_price_usd']))
print('unique slugs:', len(set(r['website_slug'] for r in out_rows)), '| unique ssp_skus:', len(set(r['ssp_sku'] for r in out_rows)))
print('written:', OUT)
