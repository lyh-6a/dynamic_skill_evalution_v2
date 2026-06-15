import json
with open('/root/input.json','r',encoding='utf-8') as f:
    data = json.load(f)
with open('/root/result.json','w',encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
