import os, re

OUT = '/root/result.pdf'

class TestOutputs:
    def test_file_exists(self):
        assert os.path.exists(OUT), 'PDF output not found'
        assert os.path.getsize(OUT) > 100, 'PDF file too small to be valid'

    def test_pdf_header(self):
        with open(OUT, 'rb') as f:
            head = f.read(5)
        assert head == b'%PDF-', 'File does not start with PDF header'

    def test_page_count_and_order(self):
        try:
            import pdfplumber
        except Exception as e:
            raise AssertionError(f'pdfplumber not available: {e}')
        expected = ['ALPHA-PAGE-ONE-7421', 'BETA-PAGE-TWO-3856', 'GAMMA-PAGE-THREE-9012']
        with pdfplumber.open(OUT) as pdf:
            assert len(pdf.pages) == len(expected), f'Expected {len(expected)} pages, got {len(pdf.pages)}'
            texts = []
            for p in pdf.pages:
                t = p.extract_text() or ''
                texts.append(t)
        for i, exp in enumerate(expected):
            assert exp in texts[i], f'Page {i+1} missing expected text {exp!r}; got {texts[i]!r}'

    def test_order_strict(self):
        try:
            import pdfplumber
        except Exception as e:
            raise AssertionError(f'pdfplumber not available: {e}')
        expected = ['ALPHA-PAGE-ONE-7421', 'BETA-PAGE-TWO-3856', 'GAMMA-PAGE-THREE-9012']
        with pdfplumber.open(OUT) as pdf:
            full = '\n'.join((p.extract_text() or '') for p in pdf.pages)
        positions = [full.find(e) for e in expected]
        for idx, pos in enumerate(positions):
            assert pos >= 0, f'Missing {expected[idx]!r} in PDF text'
        assert positions == sorted(positions), f'Pages out of order: {positions}'
