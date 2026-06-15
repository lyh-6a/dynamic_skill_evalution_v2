import json, os

class TestOutputs:
    def test_file(self):
        path = '/root/result.json'
        assert os.path.exists(path), 'result.json missing'
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert 'content' in data
        assert 'line_count' in data
        assert 'headings' in data

        content = data['content']
        assert isinstance(content, str)
        # fidelity: full markdown markers preserved
        assert '# 报告 Title' in content
        assert '## 小节 A' in content
        assert '## 小节 B' in content
        assert '- 项目 1' in content
        assert '- 项目 2' in content
        # encoding robustness: non-ascii preserved
        assert 'café 100%' in content

        # completeness via line count
        assert data['line_count'] == 11

        # correctness of headings extraction
        assert data['headings'] == ['报告 Title', '小节 A', '小节 B']
