import json, hashlib, zipfile, os, re
from docx import Document

DOCX = '/root/input.docx'
OUT = '/root/result.json'

doc = Document(DOCX)
paragraphs = []
for p in doc.paragraphs:
    t = p.text
    if t and t.strip():
        paragraphs.append(t)

images = []
with zipfile.ZipFile(DOCX, 'r') as z:
    media = sorted([n for n in z.namelist() if n.startswith('word/media/')])
    for n in media:
        data = z.read(n)
        images.append({
            'sha256': hashlib.sha256(data).hexdigest(),
            'size': len(data),
        })

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'paragraphs': paragraphs, 'images': images}, f, ensure_ascii=False, indent=2)
