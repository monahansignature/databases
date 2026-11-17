import sys, json
sys.path.insert(0,'/home/hatch/workspace/signature-school-products/shopify-skeleton')
from shopify_helper import call

print('schema:', json.dumps(call('graphql_schema',{'operation':'query','search':'menu'}))[:600], flush=True)
Q="query { menus(first: 10) { nodes { id title handle items { id title url resourceId } } } }"
v=call('validate_graphql_codeblocks',{'codeblocks':[{'code':Q,'api':'admin-execution'}]})
print('validate query:', json.dumps(v)[:300], flush=True)
r=call('graphql_query',{'query':Q})
print('menus:', json.dumps(r)[:1200], flush=True)
nodes=r.get('data',{}).get('menus',{}).get('nodes',[])
main=[m for m in nodes if m.get('handle')=='main-menu']
if not main:
    print('no main-menu found; skipping'); sys.exit(0)
main=main[0]
items=[
 {'title':'Home','url':'/'},
 {'title':'Catalog','url':'/collections'},
 {'title':'Chairs & Seating','url':'/collections/chairs-seating'},
 {'title':'Tables','url':'/collections/tables'},
 {'title':'Desks','url':'/collections/desks'},
 {'title':'Storage','url':'/collections/storage'},
 {'title':'Get a Quote','url':'/pages/get-a-quote'},
]
M="""mutation MenuUpdate($id: ID!, $title: String!, $items: [MenuItemUpdateInput!]!) {
  menuUpdate(id: $id, title: $title, items: $items) { menu { id title handle items { title url } } userErrors { field message } }
}"""
v=call('validate_graphql_codeblocks',{'codeblocks':[{'code':M,'api':'admin-execution'}]})
print('validate mutation:', json.dumps(v)[:300], flush=True)
r=call('graphql_mutation',{'query':M,'variables':{'id':main['id'],'title':main['title'],'items':items}})
print('update:', json.dumps(r)[:1000], flush=True)
r=call('graphql_query',{'query':Q})
for m in r.get('data',{}).get('menus',{}).get('nodes',[]):
    if m.get('handle')=='main-menu': print('readback main-menu:', [(i['title'],i['url']) for i in m['items']], flush=True)
