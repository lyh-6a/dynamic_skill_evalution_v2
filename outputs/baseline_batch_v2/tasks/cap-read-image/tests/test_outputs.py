import json, os, re

OUT = '/root/result.json'

def _norm(s):
    return re.sub(r'\s+', ' ', s).strip().lower()

class TestOutputs:
    def test_file_exists(self):
        assert os.path.exists(OUT), f'missing {OUT}'

    def test_json_shape(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'title' in data and isinstance(data['title'], str)
        assert 'lines' in data and isinstance(data['lines'], list)
        for ln in data['lines']:
            assert isinstance(ln, str)

    def test_title(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert _norm(data['title']) == _norm('Quarterly Report')

    def test_completeness_line_count(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert len(data['lines']) == 4, f"expected 4 body lines, got {len(data['lines'])}"

    def test_lines_content(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        expected = [
            'Revenue: 12345',
            'Expenses: 6789',
            'Profit: 5556',
            'Status: Approved',
        ]
        got = [_norm(x) for x in data['lines']]
        exp = [_norm(x) for x in expected]
        assert got == exp, f'lines mismatch: {got} vs {exp}'

    def test_numbers_preserved(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        joined = ' '.join(data['lines'])
        for token in ['12345', '6789', '5556']:
            assert token in joined, f'missing token {token} in OCR output'
