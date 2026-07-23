from fastapi.testclient import TestClient
from app.main import app


def test_dashboard_is_served():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "SSD 性能测试" in response.text
    assert 'id="block-size"' in response.text
    assert 'id="queue-button"' in response.text
    assert 'id="start-batch-button"' in response.text
