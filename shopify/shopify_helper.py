import json, subprocess
def call(tool,args,timeout=120):
    p=subprocess.run(['/opt/hatch/bin/shopify','call-tool','--name',tool,'--arguments-json', json.dumps(args)], capture_output=True, text=True, timeout=timeout)
    d=json.loads(p.stdout)
    texts=[c.get('text','') for c in d.get('result',{}).get('content',[])]
    if not texts: return d
    big=max(texts,key=len)
    if '{' not in big: return {'raw':big}
    js=big[big.index('{'):]
    try:
        obj,_=json.JSONDecoder().raw_decode(js); return obj
    except Exception:
        return {'raw':big[:2000]}
