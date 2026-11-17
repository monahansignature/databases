import sys, json
sys.path.insert(0,'/home/hatch/workspace/signature-school-products/shopify-skeleton')
from shopify_helper import call

QUOTE = "<p>Every product is available by quote — pricing, delivery, and installation provided typically within one business day. Email zach@signatureschoolproducts.com or use our Get a Quote page.</p>"
cols = [
 ("Chairs & Seating", "TAG", "Seating", "<p>Classroom chairs, task chairs, and seating for students and staff.</p>"+QUOTE),
 ("Tables", "TAG", "Tables", "<p>Activity tables, shape tables, and student tables in a range of sizes and finishes.</p>"+QUOTE),
 ("Desks", "TAG", "Desks", "<p>Student desks, teacher desks, and workstations.</p>"+QUOTE),
 ("Storage", "TAG", "Storage", "<p>Cabinets, shelving, and classroom storage.</p>"+QUOTE),
 ("Science & STEM", "TAG", "Science & STEM", "<p>Science lab and STEM furniture and equipment.</p>"+QUOTE),
 ("Accessories", "TAG", "Accessories", "<p>Desk and classroom accessories.</p>"+QUOTE),
 ("Classroom", "TAG", "Classroom", "<p>Furniture and equipment for general classrooms, Preschool through High School.</p>"+QUOTE),
 ("Library & Media Center", "TAG", "Library & Media Center", "<p>Tables, seating, and furnishings for libraries and media centers.</p>"+QUOTE),
 ("Science Lab", "TAG", "Science Lab", "<p>Furniture built for science labs and STEM spaces.</p>"+QUOTE),
 ("Music Room", "TAG", "Music Room", "<p>Instrument storage and music room furnishings.</p>"+QUOTE),
 ("Office & Staff", "TAG", "Office", "<p>Desks, chairs, and furnishings for offices and staff spaces.</p>"+QUOTE),
 ("Artcobell", "TAG", "supplier:Artcobell", "<p>School furniture from Artcobell (Temple, TX).</p>"+QUOTE),
 ("Made by Marco", "TAG", "supplier:Made by Marco", "<p>Classroom furniture from Made by Marco.</p>"+QUOTE),
 ("Offices To Go", "TAG", "supplier:Offices To Go", "<p>Office seating and desking from Offices To Go.</p>"+QUOTE),
]
results=[]
for title, col, cond, desc in cols:
    r = call('create-collection', {'title': title, 'descriptionHtml': desc,
        'ruleSet': {'appliedDisjunctively': False, 'rules': [{'column': col, 'relation': 'EQUALS', 'condition': cond}]},
        'sortOrder': 'ALPHA_ASC'})
    # parse collection id/handle from result
    txt = json.dumps(r)
    import re
    m = re.search(r'gid://shopify/Collection/\d+', txt)
    err = 'userErrors' in txt and '[]' not in txt.split('userErrors')[1][:10]
    results.append({'title': title, 'gid': m.group(0) if m else '', 'raw': txt[:220]})
    print(title, '->', m.group(0) if m else txt[:220], flush=True)
json.dump(results, open('/home/hatch/workspace/signature-school-products/shopify-skeleton/collections_created.json','w'), indent=1)
print('done', len(results))
