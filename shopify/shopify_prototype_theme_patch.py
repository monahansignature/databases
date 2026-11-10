import json, subprocess, sys
sys.path.insert(0,'/tmp'); from gql_ops import OPS
PROTO='gid://shopify/OnlineStoreTheme/198286213403'

# ---------- patch price.liquid ----------
price = open('/tmp/theme_blocks_price.liquid').read()
a1 = "  assign selected_variant = product_resource.selected_or_first_available_variant\n-%}"
assert a1 in price
price = price.replace(a1, a1 + "\n{%- liquid\n  assign ssp_quote_only = false\n  if product_resource.metafields.ssp.quote_only.value\n    assign ssp_quote_only = true\n  endif\n-%}", 1)
a2 = "\n<product-price"
assert a2 in price
price = price.replace(a2, "\n{% unless ssp_quote_only %}\n<product-price", 1)
a3 = "</product-price>"
assert a3 in price
price = price.replace(a3, "</product-price>\n{% endunless %}", 1)
open('/tmp/patched_price.liquid','w').write(price)
print('price.liquid patched, len', len(price), flush=True)

# ---------- patch buy-buttons.liquid ----------
bb = open('/tmp/theme_blocks_buy-buttons.liquid').read()
b1 = "  endif\n%}\n\n<span"
assert b1 in bb
bb = bb.replace(b1, "  endif\n%}\n{%- liquid\n  assign ssp_quote_only = false\n  if product.metafields.ssp.quote_only.value\n    assign ssp_quote_only = true\n  endif\n-%}\n\n<span", 1)
b2 = "  {%- if product != blank -%}"
assert bb.count(b2) == 1
quote_branch = """  {%- if product != blank and ssp_quote_only -%}
    <div class="ssp-quote-box" style="display:grid;gap:12px;">
      <a href="/pages/get-a-quote?product={{ product.title | url_encode }}&amp;sku={{ variant.sku }}" class="button button--primary" style="text-align:center;text-decoration:none;">Get a Quote</a>
      <p style="margin:0;">Pricing, delivery, and installation provided by quote \u2014 typically within one business day.</p>
      {%- if product.metafields.ssp.dimensions.value != blank or product.metafields.ssp.supplier_sku.value != blank -%}
        <dl class="ssp-specs" style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0;">
          {%- if product.metafields.ssp.supplier_sku.value != blank -%}<dt><strong>Model</strong></dt><dd style="margin:0;">{{ product.metafields.ssp.supplier_sku.value }}</dd>{%- endif -%}
          {%- if product.metafields.ssp.dimensions.value != blank -%}<dt><strong>Dimensions</strong></dt><dd style="margin:0;">{{ product.metafields.ssp.dimensions.value }}</dd>{%- endif -%}
          {%- if product.metafields.ssp.subcategory.value != blank -%}<dt><strong>Type</strong></dt><dd style="margin:0;">{{ product.metafields.ssp.subcategory.value }}</dd>{%- endif -%}
          {%- if product.metafields.ssp.spec_sheet_url.value != blank -%}<dt><strong>Specs</strong></dt><dd style="margin:0;"><a href="{{ product.metafields.ssp.spec_sheet_url.value }}" target="_blank" rel="noopener">Spec sheet</a></dd>{%- endif -%}
        </dl>
      {%- endif -%}
    </div>
  {%- elsif product != blank -%}"""
bb = bb.replace(b2, quote_branch, 1)
open('/tmp/patched_buy-buttons.liquid','w').write(bb)
print('buy-buttons.liquid patched, len', len(bb), flush=True)

# ---------- upsert into prototype theme ----------
def call(tool, args, timeout=200):
    try:
        p=subprocess.run(['/opt/hatch/bin/shopify','call-tool','--name',tool,'--arguments-json', json.dumps(args)], capture_output=True, text=True, timeout=timeout)
        d=json.loads(p.stdout)
        big=max((c.get('text','') for c in d['result']['content']), key=len)
        js=big[big.index('{'):] if '{' in big else big
        try: return json.loads(js)
        except Exception: return {'raw': big[:400]}
    except subprocess.TimeoutExpired:
        return {'timeout': True}
files=[{'filename': 'blocks/price.liquid', 'body': {'type': 'TEXT', 'value': price}},
       {'filename': 'blocks/buy-buttons.liquid', 'body': {'type': 'TEXT', 'value': bb}}]
r=call('graphql_mutation', {'query': OPS['theme_files_upsert'], 'variables': {'themeId': PROTO, 'files': files}})
tu=r.get('data',{}).get('themeFilesUpsert',{}) if isinstance(r,dict) else {}
print('upsert:', tu.get('upsertedThemeFiles') or tu.get('userErrors') or ('timeout?' if r.get('timeout') else str(r)[:300]), flush=True)

# verify readback from prototype theme
r=call('graphql_query', {'query': OPS['theme_files'], 'variables': {'id': PROTO, 'filenames': ['blocks/price.liquid','blocks/buy-buttons.liquid']}, 'first': 5}, timeout=60)
try:
    for n in r['data']['theme']['files']['nodes']:
        c=n['body']['content']
        print('readback', n['filename'], '| has ssp_quote_only:', 'ssp_quote_only' in c, '| has Get a Quote:', 'Get a Quote' in c, flush=True)
except Exception: print('readback failed:', str(r)[:300], flush=True)
print('step4 done', flush=True)
