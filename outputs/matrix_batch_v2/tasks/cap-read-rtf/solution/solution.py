import json, re, os

INPUT = '/root/input.rtf'
OUTPUT = '/root/result.json'

with open(INPUT, 'r', encoding='utf-8', errors='replace') as f:
    data = f.read()

# Strip header font tables / stylesheets etc inside braces with control words
# Simple RTF stripper:
# 1. Replace \par and \line with \n
# 2. Decode \uN? unicode escapes
# 3. Remove other control words
# 4. Remove braces

def decode_unicode(s):
    def repl(m):
        n = int(m.group(1))
        if n < 0:
            n += 65536
        return chr(n)
    # \uN? where ? is one fallback char (we strip the fallback)
    return re.sub(r'\\u(-?\d+)\??', repl, s)

# Remove font tables and similar groups: {\fonttbl ...}
def remove_group(text, keyword):
    pattern = re.compile(r'\{\\' + keyword + r'[^{}]*(?:\{[^{}]*\}[^{}]*)*\}')
    prev = None
    while prev != text:
        prev = text
        text = pattern.sub('', text)
    return text

for kw in ['fonttbl', 'colortbl', 'stylesheet', 'info', 'pict']:
    data = remove_group(data, kw)

# Replace paragraph/line breaks
data = re.sub(r'\\par\b ?', '\n', data)
data = re.sub(r'\\line\b ?', '\n', data)

# Decode unicode escapes
data = decode_unicode(data)

# Remove other control words like \rtf1, \ansi, \deff0 etc.
data = re.sub(r'\\[a-zA-Z]+-?\d* ?', '', data)

# Remove escaped braces / backslashes
data = data.replace('\\{', '{').replace('\\}', '}').replace('\\\\', '\\')

# Remove remaining braces
data = data.replace('{', '').replace('}', '')

# Strip leading/trailing whitespace, collapse excessive blank lines
lines = [ln.strip() for ln in data.split('\n')]
lines = [ln for ln in lines if ln]
text = '\n'.join(lines)

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump({'text': text}, f, ensure_ascii=False)
