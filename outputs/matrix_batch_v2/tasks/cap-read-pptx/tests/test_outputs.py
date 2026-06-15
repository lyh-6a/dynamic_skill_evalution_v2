import json, os

class TestOutputs:
    def setup_method(self):
        self.path = '/root/result.json'
        assert os.path.exists(self.path), 'result.json missing'
        with open(self.path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

    def test_slide_count(self):
        assert self.data.get('slide_count') == 3
        assert isinstance(self.data.get('slides'), list)
        assert len(self.data['slides']) == 3

    def test_indices_in_order(self):
        idxs = [s['index'] for s in self.data['slides']]
        assert idxs == [1, 2, 3]

    def test_slide1_content(self):
        t = self.data['slides'][0]['text']
        assert '项目周报 Q3' in t
        assert '负责人: 李雷' in t
        assert '状态: 进行中' in t

    def test_slide2_unicode(self):
        t = self.data['slides'][1]['text']
        assert 'Roadmap Übersicht' in t
        assert 'Milestone α: 2024-07' in t
        assert 'Milestone β: 2024-09' in t

    def test_slide3_content(self):
        t = self.data['slides'][2]['text']
        assert '结论 Summary' in t
        assert '完成度 78%' in t
        assert '下一步: 上线灰度' in t

    def test_no_cross_contamination(self):
        t1 = self.data['slides'][0]['text']
        assert 'Milestone' not in t1
        assert '结论' not in t1
        t2 = self.data['slides'][1]['text']
        assert '李雷' not in t2
        assert '灰度' not in t2
