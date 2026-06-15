import json, re
from html.parser import HTMLParser

class BodyExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_body = False
        self.skip_depth = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'body':
            self.in_body = True
        elif tag in ('script', 'style'):
            self.skip_depth += 1
    def handle_endtag(self, tag):
        if tag == 'body':
            self.in_body = False
        elif tag in ('script', 'style'):
            if self.skip_depth > 0:
                self.skip_depth -= 1
    def handle_data(self, data):
        if self.in_body and self.skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text)

with open('/root/input.html', 'r', encoding='utf-8') as f:
    html = f.read()
p = BodyExtractor()
p.feed(html)
body_text = ' '.join(p.parts)
body_text = re.sub(r'\s+', ' ', body_text).strip()
with open('/root/result.json', 'w', encoding='utf-8') as f:
    json.dump({'body_text': body_text}, f, ensure_ascii=False)
