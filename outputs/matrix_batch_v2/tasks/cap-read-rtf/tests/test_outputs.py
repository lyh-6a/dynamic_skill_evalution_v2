import json, os

class TestOutputs:
    def test_file(self):
        path = '/root/result.json'
        assert os.path.exists(path), 'result.json missing'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'text' in data
        text = data['text']
        assert isinstance(text, str)
        # correctness / completeness: each expected line present
        assert 'Hello, World!' in text
        assert 'This is a tiny RTF document.' in text
        # encoding_robustness: non-ASCII preserved
        assert 'Café costs 5 euros.' in text
        # fidelity: no RTF control artifacts
        assert '\\par' not in text
        assert '\\rtf' not in text
        assert '{' not in text
        assert '}' not in text
        # line break between paragraphs
        assert 'Hello, World!\nThis is a tiny RTF document.' in text
