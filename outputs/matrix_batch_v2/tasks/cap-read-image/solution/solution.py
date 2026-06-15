import json, os, re

IMG_PATH = '/root/input.png'
OUT_PATH = '/root/result.json'

def extract_text(image_path):
    # Try pytesseract first
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(image_path))
        return text
    except Exception:
        pass
    # Fallback: easyocr
    try:
        import easyocr
        reader = easyocr.Reader(['en'], gpu=False)
        results = reader.readtext(image_path, detail=0, paragraph=False)
        return '\n'.join(results)
    except Exception:
        pass
    return ''

text = extract_text(IMG_PATH)
raw_lines = [l.strip() for l in text.splitlines() if l.strip()]

if raw_lines:
    title = raw_lines[0]
    lines = raw_lines[1:]
else:
    title = ''
    lines = []

result = {
    'title': title,
    'lines': lines,
}

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
