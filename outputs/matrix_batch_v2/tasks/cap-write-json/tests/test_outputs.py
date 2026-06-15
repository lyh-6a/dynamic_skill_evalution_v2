import json, os

class TestOutputs:
    def test_file(self):
        path = '/root/result.json'
        assert os.path.exists(path), 'output file missing'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict), 'top-level must be object'
        assert data.get('title') == 'Sample Report'
        assert data.get('count') == 3
        assert isinstance(data.get('count'), int) and not isinstance(data.get('count'), bool)
        assert data.get('tags') == ['alpha', 'beta', 'gamma']
        meta = data.get('meta')
        assert isinstance(meta, dict)
        assert meta.get('author') == 'Alice'
        assert meta.get('version') == 1
        assert set(data.keys()) == {'title', 'count', 'tags', 'meta'}
