import json

data = {
    "title": "Sample Report",
    "count": 3,
    "tags": ["alpha", "beta", "gamma"],
    "meta": {
        "author": "Alice",
        "version": 1
    }
}

with open('/root/result.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
