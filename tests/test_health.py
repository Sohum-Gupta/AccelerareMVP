def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_admin_login_page_renders(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
