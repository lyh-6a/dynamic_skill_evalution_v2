import json, os

class TestOutputs:
    def test_file(self):
        path = '/root/result.json'
        assert os.path.exists(path), 'result.json not found'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'text' in data and isinstance(data['text'], str)
        text = data['text']
        # correctness & completeness: each expected paragraph appears
        assert 'Hello ODT World' in text
        assert 'Line three: 42 items.' in text
        # fidelity: special punctuation and accents preserved
        assert 'Café résumé naïve' in text
        assert '—' in text
        # encoding_robustness: non-ASCII CJK preserved
        assert '你好，世界' in text
        # order preserved
        i1 = text.find('Hello ODT World')
        i2 = text.find('Café résumé naïve')
        i3 = text.find('Line three: 42 items.')
        assert 0 <= i1 < i2 < i3
