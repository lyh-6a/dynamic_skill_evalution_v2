import json

with open('/root/input.md', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
line_count = len(lines)

headings = []
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith('#'):
        # strip leading #s and spaces
        h = stripped.lstrip('#').strip()
        if h:
            headings.append(h)

result = {
    'content': content,
    'line_count': line_count,
    'headings': headings,
}

with open('/root/result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
