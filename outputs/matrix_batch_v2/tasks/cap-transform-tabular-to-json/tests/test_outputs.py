import json, os

class TestOutputs:
    def test_file(self):
        path = '/root/result.json'
        assert os.path.exists(path), 'result.json missing'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # structure_fidelity: array of 3 objects
        assert isinstance(data, list), 'top-level must be a list'
        assert len(data) == 3, f'expected 3 rows, got {len(data)}'
        for item in data:
            assert isinstance(item, dict), 'each row must be an object'
            assert set(item.keys()) == {'id', 'name', 'score'}, f'unexpected keys: {item.keys()}'
        # value_preservation: every cell preserved
        expected = [
            {'id': '1', 'name': 'alpha', 'score': '85'},
            {'id': '2', 'name': 'beta', 'score': '92'},
            {'id': '3', 'name': 'gamma', 'score': '78'},
        ]
        norm = [{k: str(v) for k, v in row.items()} for row in data]
        assert norm == expected, f'row content mismatch: {norm}'
