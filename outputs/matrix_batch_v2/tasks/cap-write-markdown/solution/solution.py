import json

with open('/root/content.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

title = data['title']
items = data['items']
scores = data['scores']

lines = []
lines.append(f'# {title}')
lines.append('')
lines.append('## Items')
lines.append('')
for it in items:
    lines.append(f'- {it}')
lines.append('')
lines.append('## Scores')
lines.append('')
lines.append('Name | Score')
lines.append('--- | ---')
for row in scores:
    lines.append(f"{row['name']} | {row['score']}")
lines.append('')

with open('/root/result.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
