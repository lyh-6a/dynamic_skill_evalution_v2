import json, os, re

class TestOutputs:
    def test_file_exists(self):
        assert os.path.exists('/root/result.json'), 'result.json missing'

    def test_is_json_with_key(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert 'body_text' in data
        assert isinstance(data['body_text'], str)

    def test_contains_paragraphs(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        text = data['body_text']
        assert 'Welcome to the test page.' in text
        assert 'This paragraph contains important content.' in text
        assert 'The quick brown fox jumps over the lazy dog.' in text

    def test_no_html_tags(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        text = data['body_text']
        assert '<' not in text and '>' not in text, 'should have no html tags'

    def test_noise_removed(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        text = data['body_text']
        assert 'alert' not in text
        assert 'var x' not in text
        assert 'color: red' not in text
        assert 'console.log' not in text

    def test_title_not_included(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        text = data['body_text']
        assert 'Sample Page' not in text, 'head/title content should not be in body text'

    def test_whitespace_normalized(self):
        with open('/root/result.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        text = data['body_text']
        assert text == text.strip()
        assert '  ' not in text, 'whitespace should be collapsed'
