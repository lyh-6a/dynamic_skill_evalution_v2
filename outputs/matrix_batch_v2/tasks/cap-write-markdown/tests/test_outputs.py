import os, re

class TestOutputs:
    path = '/root/result.md'

    def _read(self):
        assert os.path.exists(self.path), 'result.md missing'
        with open(self.path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_exists_nonempty(self):
        text = self._read()
        assert len(text.strip()) > 0

    def test_h1_title(self):
        text = self._read()
        lines = [l.rstrip() for l in text.splitlines()]
        h1s = [l for l in lines if l.startswith('# ') and not l.startswith('## ')]
        assert any(l.strip() == '# Quarterly Report' for l in h1s), f'missing H1 title, got h1s={h1s}'

    def test_items_section(self):
        text = self._read()
        assert re.search(r'^##\s+Items\s*$', text, re.M), 'missing ## Items heading'
        for it in ['Revenue grew', 'Costs stable', 'Headcount +3']:
            assert re.search(r'^-\s+' + re.escape(it) + r'\s*$', text, re.M), f'missing list item: {it}'

    def test_scores_section_and_table_header(self):
        text = self._read()
        assert re.search(r'^##\s+Scores\s*$', text, re.M), 'missing ## Scores heading'
        assert re.search(r'^Name\s*\|\s*Score\s*$', text, re.M), 'missing table header'
        assert re.search(r'^-{3,}\s*\|\s*-{3,}\s*$', text, re.M), 'missing table separator row'

    def test_score_rows(self):
        text = self._read()
        for name, score in [('Alice', 91), ('Bob', 85), ('Carol', 78)]:
            pat = r'^' + re.escape(name) + r'\s*\|\s*' + str(score) + r'\s*$'
            assert re.search(pat, text, re.M), f'missing row for {name}'

    def test_section_order(self):
        text = self._read()
        i_title = text.find('# Quarterly Report')
        i_items = text.find('## Items')
        i_scores = text.find('## Scores')
        assert i_title >= 0 and i_items > i_title and i_scores > i_items, 'sections out of order'
