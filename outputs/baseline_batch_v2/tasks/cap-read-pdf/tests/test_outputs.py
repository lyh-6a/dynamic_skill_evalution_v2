import json, os

OUT = '/root/result.json'

EXPECTED = [
    'Invoice Number: INV-2024-0917',
    'Customer: Zoë Müller',
    'Amount Due: 1234.56 EUR',
    'Due Date: 2024-11-30',
    'Notes: Thank you — pay on time!',
]

class TestOutputs:
    def _load(self):
        assert os.path.exists(OUT), f'output file not found: {OUT}'
        with open(OUT, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_schema(self):
        data = self._load()
        assert isinstance(data, dict)
        assert 'lines' in data and isinstance(data['lines'], list)
        assert 'full_text' in data and isinstance(data['full_text'], str)

    def test_completeness_count(self):
        data = self._load()
        assert len(data['lines']) == len(EXPECTED), f"expected {len(EXPECTED)} lines, got {len(data['lines'])}: {data['lines']}"

    def test_correctness_lines(self):
        data = self._load()
        for i, exp in enumerate(EXPECTED):
            got = data['lines'][i].strip()
            assert got == exp, f'line {i} mismatch: expected {exp!r}, got {got!r}'

    def test_reading_order(self):
        data = self._load()
        # The first line must be the invoice header, the last must be the notes.
        assert data['lines'][0].strip() == EXPECTED[0]
        assert data['lines'][-1].strip() == EXPECTED[-1]

    def test_encoding_robustness(self):
        data = self._load()
        joined = '\n'.join(s.strip() for s in data['lines'])
        # Non-ASCII characters from the source must survive extraction.
        assert 'Zoë' in joined
        assert 'Müller' in joined
        assert '—' in joined

    def test_full_text_consistency(self):
        data = self._load()
        rebuilt = '\n'.join(s.strip() for s in data['lines'])
        assert data['full_text'].strip() == rebuilt.strip()
