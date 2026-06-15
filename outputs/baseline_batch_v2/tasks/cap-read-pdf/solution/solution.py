import json
import pdfplumber

PDF_PATH = '/root/input.pdf'
OUT_PATH = '/root/result.json'

lines = []
with pdfplumber.open(PDF_PATH) as pdf:
    for page in pdf.pages:
        text = page.extract_text() or ''
        for raw in text.split('\n'):
            s = raw.strip()
            if s:
                lines.append(s)

result = {
    'lines': lines,
    'full_text': '\n'.join(lines),
}

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
