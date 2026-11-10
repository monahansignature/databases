import json, subprocess, sys, csv, time
sys.path.insert(0,'/tmp'); from gql_ops import OPS

def call(tool, args, timeout=150):
    try:
        p=subprocess.run(['/opt/hatch/bin/shopify','call-tool','--name',tool,'--arguments-json', json.dumps(args)], capture_output=True, text=True, timeout=timeout)
        d=json.loads(p.stdout)
        texts=[c.get('text','') for c in d['result']['content']]
        big=max(texts, key=len)
        js=big[big.index('{'):] if '{' in big else big
        try: return json.loads(js)
        except Exception: return {'raw': big[:500]}
    except subprocess.TimeoutExpired:
        return {'timeout': True}
    except Exception as e:
        return {'error': str(e)}

log=[]
def note(*a):
    s=' '.join(str(x) for x in a); print(s, flush=True); log.append(s)

# ---------- 1. remaining definitions ----------
DEFS=[('show_price','boolean','SSP Show Price'),('supplier','single_line_text_field','SSP Supplier'),
 ('supplier_sku','single_line_text_field','SSP Supplier SKU / Model'),('subcategory','single_line_text_field','SSP Subcategory'),
 ('dimensions','single_line_text_field','SSP Dimensions'),('spec_sheet_url','url','SSP Spec Sheet URL'),
 ('room_tags','list.single_line_text_field','SSP Room Tags'),('grade_levels','list.single_line_text_field','SSP Grade Levels')]
for key, typ, name in DEFS:
    r=call('graphql_mutation', {'query': OPS['definition_create'], 'variables': {'definition': {
        'name': name, 'namespace': 'ssp', 'key': key, 'ownerType': 'PRODUCT', 'type': typ,
        'description': 'Signature School Products product database field (prototype)'}}})
    dc=r.get('data',{}).get('metafieldDefinitionCreate',{}) if isinstance(r,dict) else {}
    note('def', key, 'created' if dc.get('createdDefinition') else ('timeout?' if r.get('timeout') else dc.get('userErrors')))

Q_DEFS='query { metafieldDefinitions(first: 30, ownerType: PRODUCT, namespace: "ssp") { edges { node { key } } } }'
r=call('graphql_query', {'query': Q_DEFS, 'first': 5}, timeout=60)
keys=[e['node']['key'] for e in r.get('data',{}).get('metafieldDefinitions',{}).get('edges',[])]
note('definitions present:', sorted(keys))

# ---------- 2. metafield values on the 12 ----------
GIDS={'SSP-ART-0026':'10594790146331','SSP-ART-0027':'10594790736155','SSP-ART-0029':'10594790867227','SSP-ART-0001':'10594791096603',
'SSP-MAR-0001':'10594791162139','SSP-MAR-0002':'10594791260443','SSP-MAR-0003':'10594791358747','SSP-MAR-0004':'10594791457051',
'SSP-OTG-0001':'10594791555355','SSP-OTG-0002':'10594791620891','SSP-OTG-0003':'10594791719195','SSP-OTG-0085':'10594791883035'}
rows={r['ssp_sku']: r for r in csv.DictReader(open('/home/hatch/workspace/goals/signature-school-products-quote-first-catalog/files/product_database_draft.csv'))}
mfs=[]
for sku, gid in GIDS.items():
    r=rows[sku]; base={'ownerId': f'gid://shopify/Product/{gid}', 'namespace': 'ssp'}
    def add(k, t, v):
        if v is not None and str(v).strip()!='': mfs.append({**base, 'key': k, 'type': t, 'value': v})
    add('quote_only','boolean','true' if r['quote_only']=='yes' else 'false')
    add('show_price','boolean','true' if r['show_price']=='yes' else 'false')
    add('supplier','single_line_text_field', r['supplier'])
    add('supplier_sku','single_line_text_field', r['supplier_sku_model'])
    add('subcategory','single_line_text_field', r['subcategory'])
    add('dimensions','single_line_text_field', r['dimensions'])
    if r['spec_sheet_url'].startswith('http'): add('spec_sheet_url','url', r['spec_sheet_url'])
    add('room_tags','list.single_line_text_field', json.dumps([t.strip() for t in r['room_tags'].split(';') if t.strip()]))
    add('grade_levels','list.single_line_text_field', json.dumps([t.strip() for t in r['grade_levels'].split(';') if t.strip()]))
note('metafields to set:', len(mfs))
for i in range(0, len(mfs), 25):
    chunk=mfs[i:i+25]
    r=call('graphql_mutation', {'query': OPS['metafields_set'], 'variables': {'metafields': chunk}})
    ms=r.get('data',{}).get('metafieldsSet',{}) if isinstance(r,dict) else {}
    note('metafieldsSet chunk', i//25+1, 'set:', len(ms.get('metafields') or []), 'errors:', ms.get('userErrors'), 'timeout?' if r.get('timeout') else '')

Q_ONE='query { product(id: "gid://shopify/Product/10594791162139") { title metafields(first: 15, namespace: "ssp") { edges { node { key value } } } } }'
r=call('graphql_query', {'query': Q_ONE, 'first': 5}, timeout=60)
try:
    mf={e['node']['key']: e['node']['value'] for e in r['data']['product']['metafields']['edges']}
    note('verify MAR-0001 metafields:', mf)
except Exception: note('verify failed:', str(r)[:300])

# ---------- 3. themes + files ----------
r=call('graphql_query', {'query': OPS['themes_list'], 'first': 10}, timeout=60)
themes=[e['node'] for e in r.get('data',{}).get('themes',{}).get('edges',[])]
note('themes:', themes)
main=[t for t in themes if t['role']=='MAIN']
proto=[t for t in themes if 'Prototype' in t['name']]
main_id=main[0]['id'] if main else None
if main_id:
    r=call('graphql_query', {'query': OPS['theme_files'], 'variables': {'id': main_id, 'filenames': ['snippets/price.liquid','sections/main-product.liquid']}, 'first': 5}, timeout=60)
    try:
        nodes=r['data']['theme']['files']['nodes']
        for n in nodes:
            fn='/tmp/theme_'+n['filename'].replace('/','_')
            open(fn,'w').write(n['body']['content'])
            note('saved', n['filename'], len(n['body']['content']), 'chars')
    except Exception: note('theme files fetch failed:', str(r)[:300])
if proto:
    note('prototype theme already exists:', proto[0])
    json.dump({'main_id': main_id, 'proto_id': proto[0]['id']}, open('/tmp/proto_theme.json','w'))
elif main_id:
    r=call('graphql_mutation', {'query': OPS['theme_duplicate'], 'variables': {'id': main_id, 'name': 'SSP Quote Prototype'}})
    nt=r.get('data',{}).get('themeDuplicate',{}) if isinstance(r,dict) else {}
    note('themeDuplicate:', nt.get('newTheme') or nt.get('userErrors') or ('timeout?' if r.get('timeout') else r))
    r2=call('graphql_query', {'query': OPS['themes_list'], 'first': 10}, timeout=60)
    themes2=[e['node'] for e in r2.get('data',{}).get('themes',{}).get('edges',[])]
    proto2=[t for t in themes2 if 'Prototype' in t['name']]
    note('themes after duplicate:', themes2)
    if proto2: json.dump({'main_id': main_id, 'proto_id': proto2[0]['id']}, open('/tmp/proto_theme.json','w'))

# ---------- 4. quote page ----------
Q_PAGES='query { pages(first: 10) { edges { node { id title handle } } } }'
r=call('graphql_query', {'query': Q_PAGES, 'first': 10}, timeout=60)
pages=[e['node'] for e in r.get('data',{}).get('pages',{}).get('edges',[])]
note('pages:', pages)
if not any(p['handle']=='get-a-quote' for p in pages):
    body='<p>Tell us what you need and we will reply with a quote — pricing, delivery, and installation options — within one business day.</p><p>Include the product name or SKU, quantity, and your school or organization. Submissions go to our team at Signature School Products.</p>'
    r=call('graphql_mutation', {'query': OPS['page_create'], 'variables': {'page': {'title': 'Get a Quote', 'handle': 'get-a-quote', 'body': body, 'isPublished': True, 'templateSuffix': 'contact'}}})
    pc=r.get('data',{}).get('pageCreate',{}) if isinstance(r,dict) else {}
    note('pageCreate:', pc.get('page') or pc.get('userErrors') or ('timeout?' if r.get('timeout') else str(r)[:200]))
json.dump(log, open('/tmp/proto_step2_log.json','w'), indent=1)
note('step2 done')
