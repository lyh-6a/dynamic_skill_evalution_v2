import json, os

class TestOutputs:
    def _load(self):
        p = '/root/result.json'
        assert os.path.exists(p), 'result.json not found'
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_sheet_names(self):
        d = self._load()
        names = d.get('sheet_names') or list((d.get('sheets') or {}).keys())
        assert 'Sales' in names
        assert '用户' in names

    def test_sheets_present(self):
        d = self._load()
        sheets = d.get('sheets', {})
        assert 'Sales' in sheets
        assert '用户' in sheets

    def test_sales_dimensions(self):
        d = self._load()
        sales = d['sheets']['Sales']
        assert len(sales) == 3
        for row in sales:
            assert len(row) == 3

    def test_sales_values(self):
        d = self._load()
        sales = d['sheets']['Sales']
        assert sales[0][0] == 'Region'
        assert sales[0][1] == 'Q1'
        assert sales[0][2] == 'Q2'
        assert sales[1][0] == 'North'
        assert str(sales[1][1]) == '120'
        assert str(sales[1][2]) == '150'
        assert sales[2][0] == 'South'
        assert str(sales[2][1]) == '90'
        assert str(sales[2][2]) == '110'

    def test_users_dimensions(self):
        d = self._load()
        users = d['sheets']['用户']
        assert len(users) == 3
        for row in users:
            assert len(row) == 2

    def test_users_values(self):
        d = self._load()
        users = d['sheets']['用户']
        assert users[0][0] == '姓名'
        assert users[0][1] == '年龄'
        assert users[1][0] == '张三'
        assert str(users[1][1]) == '28'
        assert users[2][0] == '李四'
        assert str(users[2][1]) == '35'

    def test_separation(self):
        d = self._load()
        # sheets must be separated, not merged into one blob
        assert isinstance(d['sheets']['Sales'], list)
        assert isinstance(d['sheets']['用户'], list)
        assert d['sheets']['Sales'] != d['sheets']['用户']
