import csv, json, subprocess, html

rows = list(csv.DictReader(open('/home/hatch/workspace/goals/signature-school-products-quote-first-catalog/files/product_database_draft.csv')))

def pick(supplier, pred, n, used):
    out=[]
    for r in rows:
        if r['supplier']==supplier and pred(r) and r['ssp_sku'] not in used:
            out.append(r); used.add(r['ssp_sku'])
            if len(out)==n: break
    return out

used=set(); sample=[]
sample += pick('Artcobell', lambda r: r['publish']=='yes', 3, used)                       # has images
sample += pick('Artcobell', lambda r: r['category']=='Tables', 1, used)                    # no image (expected)
sample += pick('Made by Marco', lambda r: r['publish']=='yes', 4, used)                    # unpriced
sample += pick('Offices To Go', lambda r: r['publish']=='yes' and r['category']=='Seating', 3, used)
sample += pick('Offices To Go', lambda r: r['publish']=='yes' and r['category']=='Desks', 1, used)
print('sample:', [(r['ssp_sku'], r['supplier'], r['category'], bool(r['image_url']), r['ssp_price_usd']) for r in sample])

def tags_for(r):
    tags = ['ssp-test', 'quote-only', 'show-price-no', r['category'], r['subcategory'], f"supplier:{r['supplier']}", f"model:{r['supplier_sku_model']}"]
    tags += [t.strip() for t in r['room_tags'].split(';')]
    tags += [t.strip() for t in r['grade_levels'].split(';')]
    return tags

results=[]
for r in sample:
    desc = f"<p>{html.escape(r['short_description'])}</p>"
    if r['dimensions']: desc += f"<p><strong>Dimensions:</strong> {html.escape(r['dimensions'])}</p>"
    desc += f"<p><strong>Model:</strong> {html.escape(r['supplier_sku_model'])} · <strong>SSP SKU:</strong> {r['ssp_sku']}</p>"
    if r['spec_sheet_url']: desc += f"<p><a href=\"{r['spec_sheet_url']}\">Spec sheet</a></p>"
    args = {
        'title': r['title'],
        'descriptionHtml': desc,
        'vendor': r['brand'],
        'productType': r['category'],
        'status': 'DRAFT',
        'tags': tags_for(r),
        'options': ['Title'],
        'variants': [{'optionValues': [{'optionName':'Title','name':'Default Title'}],
                      'price': r['ssp_price_usd'] if r['ssp_price_usd'] else '0.00',
                      'sku': r['ssp_sku']}],
    }
    if r['image_url']:
        args['images'] = [{'url': r['image_url'], 'altText': r['title']}]
    p = subprocess.run(['/opt/hatch/bin/shopify','call-tool','--name','create-product','--arguments-json', json.dumps(args)],
                       capture_output=True, text=True, timeout=120)
    out = p.stdout.strip()
    ok = '"ok":true' in out or '"ok": true' in out
    gid = ''
    try:
        d = json.loads(out)
        res = d.get('result', d)
        txt = json.dumps(res)
        import re
        m = re.search(r'gid://shopify/Product/\d+', txt)
        gid = m.group(0) if m else ''
        if 'error' in txt.lower() and not gid: ok=False
    except Exception as e:
        ok=False
    results.append({'ssp_sku': r['ssp_sku'], 'title': r['title'], 'ok': ok, 'gid': gid, 'raw': out[:300]})
    print(('OK  ' if ok else 'FAIL'), r['ssp_sku'], gid, '' if ok else out[:200])

json.dump(results, open('/tmp/shopify_test_results.json','w'), indent=1)
print('created:', sum(1 for x in results if x['ok']), '/', len(results))
