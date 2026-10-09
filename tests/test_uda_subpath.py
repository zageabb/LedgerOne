"""Regression test for LedgerOne navigation and sign-in under UDA."""
def test_subpath_signin(client):
    headers={"X-Forwarded-Prefix":"/apps/ledgerone",
             "X-Forwarded-Host":"tanyaanne.ddns.net",
             "X-Forwarded-Proto":"https"}
    response=client.get("/",headers=headers,follow_redirects=False)
    assert response.status_code in (301,302,303,307,308)
    assert "/apps/ledgerone/" in response.headers["Location"]
    login=client.get("/auth/login",headers=headers)
    assert login.status_code==200
    body=login.get_data(as_text=True)
    assert '<base href="/apps/ledgerone/">' in body
    assert '/apps/ledgerone/static/css/ledgerone.css' in body

def test_lan_root_login(client):
    response=client.get("/auth/login")
    assert response.status_code==200
    assert '<base href="/">' in response.get_data(as_text=True)
