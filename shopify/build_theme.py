import sys, json, copy
sys.path.insert(0,'/home/hatch/workspace/signature-school-products/shopify-skeleton')
sys.path.insert(0,'/home/hatch/workspace/databases-repo/shopify')
from shopify_helper import call
from gql_ops import OPS
PROTO='gid://shopify/OnlineStoreTheme/198286213403'

def get(fn):
    r=call('graphql_query',{'query':OPS['theme_files'],'variables':{'id':PROTO,'filenames':[fn]}})
    n=r.get('data',{}).get('theme',{}).get('files',{}).get('nodes',[])
    return n[0]['body']['content'] if n else None
def parse(c): return json.loads(c[c.index('{'):])
def dump(j): return json.dumps(j, indent=2)

# ---------- generic text section builder (cloned from templates/collection.json 'section') ----------
coll_tpl = parse(get('templates/collection.json'))
section_proto = coll_tpl['sections']['section']

def text_block(text, preset='rte', name='t:names.text'):
    return {"type":"text","name":name,"settings":{
        "text":text,"width":"100%","max_width":"normal","alignment":"left","type_preset":preset,
        "font":"var(--font-body--family)","line_height":"normal","letter_spacing":"normal","case":"none","wrap":"pretty",
        "background":False,"background_color":"#00000026","corner_radius":0,
        "padding-block-start":0,"padding-block-end":0,"padding-inline-start":0,"padding-inline-end":0},"blocks":{}}

def make_section(heading, body_html, key_prefix):
    s = copy.deepcopy(section_proto)
    s['blocks'] = {
        f"{key_prefix}_h": text_block(f"<h2>{heading}</h2>", 'h2', 't:names.title'),
        f"{key_prefix}_b": text_block(body_html, 'rte', 't:names.description'),
    }
    s['block_order'] = [f"{key_prefix}_h", f"{key_prefix}_b"]
    return s

# ---------- homepage ----------
idx = parse(get('templates/index.json'))
hero = idx['sections']['hero_jVaWmY']
hero['blocks']['text_YLPk4p']['settings']['text'] = "<h1>School Furniture &amp; Equipment for Every Classroom</h1><p>Chairs, desks, tables, storage and more from trusted U.S. manufacturers — every product available by quote, typically within one business day.</p>"
hero['blocks']['button_H9gpTf']['settings']['label'] = "Get a Quote"
hero['blocks']['button_H9gpTf']['settings']['link'] = "shopify://pages/get-a-quote"
# second button: browse catalog
btn2 = copy.deepcopy(hero['blocks']['button_H9gpTf'])
btn2['settings']['label'] = "Browse the Catalog"
btn2['settings']['link'] = "shopify://collections"
hero['blocks']['button_catalog'] = btn2
hero['block_order'] = ['text_YLPk4p','button_H9gpTf','button_catalog']

# categories section: clone main-collection-list from list-collections template
lc = parse(get('templates/list-collections.json'))
cat_section = copy.deepcopy(lc['sections']['collection_list_Wfgh3m'])
cat_section['blocks']['group_4FtiAg']['blocks']['text_fRMQMR']['settings']['text'] = "<h2>Shop by Product Category</h2><p>Chairs &amp; seating, tables, desks, storage, science &amp; STEM and more.</p>"
cat_section['settings']['columns'] = 3
cat_section['settings']['max_collections'] = 16

idx['sections']['ssp_categories'] = cat_section
idx['sections']['ssp_classroom'] = make_section("Shop by Classroom",
  "<p><a href=\"/collections/classroom\">Classroom</a> &middot; <a href=\"/collections/library-media-center\">Library &amp; Media Center</a> &middot; <a href=\"/collections/science-lab\">Science Lab</a> &middot; <a href=\"/collections/music-room\">Music Room</a> &middot; <a href=\"/collections/office-staff\">Office &amp; Staff</a></p><p>Furnishing a single classroom or a whole school? Start with a category above, or <a href=\"/pages/get-a-quote\">request a quote</a> and we will help you put the room together.</p>", "room")
idx['sections']['ssp_brands'] = make_section("Shop by Brand",
  "<p><a href=\"/collections/artcobell\">Artcobell</a> &middot; <a href=\"/collections/made-by-marco\">Made by Marco</a> &middot; <a href=\"/collections/offices-to-go\">Offices To Go</a></p><p>We represent U.S.-based manufacturers known for quality and warranty service, and we sell the full catalogues of our suppliers.</p>", "brand")
idx['sections']['ssp_quote_cta'] = make_section("Get a Quote in One Business Day",
  "<p>Tell us what you need — a single product, a classroom set, or a full school. We will reply with pricing, delivery, and installation options, typically within one business day.</p><p>Purchase orders and tax-exempt purchasing welcome. Email <a href=\"mailto:zach@signatureschoolproducts.com\">zach@signatureschoolproducts.com</a> or use the <a href=\"/pages/get-a-quote\">Get a Quote page</a>.</p>", "cta")
idx['order'] = ['hero_jVaWmY','ssp_categories','product_list_fa6P9H','ssp_classroom','ssp_brands','ssp_quote_cta']

# ---------- catalog index (/collections) ----------
lc['sections']['collection_list_Wfgh3m']['blocks']['group_4FtiAg']['blocks']['text_fRMQMR']['settings']['text'] = "<h1>Catalog</h1><p>Shop by product category, classroom type, or brand. Every product is available by quote — pricing, delivery, and installation provided typically within one business day.</p>"
lc['sections']['collection_list_Wfgh3m']['settings']['columns'] = 3
lc['sections']['collection_list_Wfgh3m']['settings']['max_collections'] = 16

files=[{'filename':'templates/index.json','body':{'type':'TEXT','value':dump(idx)}},
       {'filename':'templates/list-collections.json','body':{'type':'TEXT','value':dump(lc)}}]
r=call('graphql_mutation',{'query':OPS['theme_files_upsert'],'variables':{'themeId':PROTO,'files':files}})
tu=r.get('data',{}).get('themeFilesUpsert',{}) if isinstance(r,dict) else {}
print('upsert:', tu.get('upsertedThemeFiles') or tu.get('userErrors') or str(r)[:400], flush=True)

# readback verify
for fn, needles in [('templates/index.json',['School Furniture','Shop by Product Category','Shop by Classroom','Shop by Brand','Get a Quote in One Business Day']),
                    ('templates/list-collections.json',['Catalog','Shop by product category'])]:
    c=get(fn) or ''
    print(fn, {n: (n in c) for n in needles}, flush=True)
print('theme build done')
