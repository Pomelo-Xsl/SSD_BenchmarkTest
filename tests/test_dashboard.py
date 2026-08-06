from fastapi.testclient import TestClient
from app.main import app


def test_dashboard_is_served():
    client = TestClient(app)
    assert "选择要执行的功能" in client.get("/").text


def test_feature_pages_are_served():
    client = TestClient(app)
    for path, title in [("/devices", "设备扫描"), ("/tests", "单项测试"), ("/queue", "批量测试"), ("/results", "结果查询")]:
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text
