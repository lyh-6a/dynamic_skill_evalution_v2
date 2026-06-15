import json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

with open('/root/pages.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

pages = data['pages']
out = '/root/result.pdf'
c = canvas.Canvas(out, pagesize=letter)
width, height = letter
for text in pages:
    c.setFont('Helvetica', 14)
    c.drawString(72, height - 100, text)
    c.showPage()
c.save()
