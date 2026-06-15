import json, os, hashlib

OUT = '/root/result.json'

class TestOutputs:
    def test_file_exists(self):
        assert os.path.exists(OUT), 'output not found'

    def test_paragraphs(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        expected = [
            '你好，世界 — Hello, World!',
            '第二段：包含特殊字符 © ™ €。',
            'Third paragraph with mixed ASCII.',
            '末段结束。',
        ]
        assert 'paragraphs' in data
        assert data['paragraphs'] == expected, f"paragraphs mismatch: {data['paragraphs']}"

    def test_images_count(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert 'images' in data
        assert len(data['images']) == 2, f"expected 2 images, got {len(data['images'])}"

    def test_images_have_hash_and_size(self):
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for img in data['images']:
            assert 'sha256' in img and isinstance(img['sha256'], str)
            assert len(img['sha256']) == 64
            assert 'size' in img and isinstance(img['size'], int) and img['size'] > 0

    def test_images_sizes_distinct(self):
        # The two embedded images have different dimensions/colors -> different bytes
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        hashes = [i['sha256'] for i in data['images']]
        assert len(set(hashes)) == 2, 'image hashes should differ'

    def test_images_bytes_match_docx(self):
        import zipfile
        with open(OUT, 'r', encoding='utf-8') as f:
            data = json.load(f)
        with zipfile.ZipFile('/root/input.docx', 'r') as z:
            media = sorted([n for n in z.namelist() if n.startswith('word/media/')])
            expected = []
            for n in media:
                b = z.read(n)
                expected.append({'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b)})
        assert data['images'] == expected, f"images mismatch: {data['images']} vs {expected}"
