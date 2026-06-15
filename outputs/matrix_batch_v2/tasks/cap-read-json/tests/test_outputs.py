import json, os
class TestOutputs:
    def test_file(self):
        p = '/root/result.json'
        assert os.path.exists(p), 'result.json missing'
        with open(p,'r',encoding='utf-8') as f:
            d = json.load(f)
        assert isinstance(d, dict), 'top-level must be object'
        assert d.get('id') == 42
        assert d.get('name') == 'widget'
        assert abs(float(d.get('price')) - 19.95) < 1e-2
        assert d.get('in_stock') is True
        assert d.get('tags') == ['alpha','beta']
        meta = d.get('meta')
        assert isinstance(meta, dict)
        assert abs(float(meta.get('weight')) - 1.5) < 1e-2
        assert meta.get('color') == 'red'
