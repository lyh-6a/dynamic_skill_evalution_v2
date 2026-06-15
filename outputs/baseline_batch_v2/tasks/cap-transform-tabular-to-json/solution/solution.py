import csv, json
rows_out = []
with open('/root/input.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows_out.append({k: v for k, v in row.items()})
with open('/root/result.json', 'w', encoding='utf-8') as f:
    json.dump(rows_out, f, ensure_ascii=False, indent=2)
