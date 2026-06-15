import json, zipfile
import xml.etree.ElementTree as ET

INPUT = '/root/input.odt'
OUTPUT = '/root/result.json'

NS_TEXT = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'

with zipfile.ZipFile(INPUT, 'r') as z:
    with z.open('content.xml') as f:
        tree = ET.parse(f)
root = tree.getroot()

paragraphs = []
for p in root.iter('{%s}p' % NS_TEXT):
    # Concatenate all text within paragraph (including in child spans)
    text = ''.join(p.itertext())
    paragraphs.append(text)

text = '\n'.join(paragraphs)
with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump({'text': text}, f, ensure_ascii=False)
