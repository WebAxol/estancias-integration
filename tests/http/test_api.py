import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client(app_env):
    with TestClient(create_app(app_env), raise_server_exceptions=False) as test_client:
        yield test_client


def put_in_room(pool, email, room_id):
    with pool.connection() as conn:
        conn.execute("UPDATE Employee SET room_id = %s WHERE email = %s", (room_id, email))


def login(client, email="admin@example.com", password="admin-pass"):
    return client.post("/session", json={"email": email, "password": password})


def auth(client) -> dict:
    token = login(client).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def assert_envelope(body: dict, success: bool):
    assert body["success"] is success
    assert isinstance(body["message"], str)
    assert ("data" in body) != ("error" in body) or (success and "data" not in body and "error" not in body)
    if not success:
        assert "data" not in body and "code" in body["error"]


def test_login_success(client):
    res = login(client)
    body = res.json()
    assert res.status_code == 200
    assert_envelope(body, True)
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["access_token"] and body["data"]["expires_at"]


def test_login_returns_profile_with_permissions(client):
    profile = login(client).json()["data"]["profile"]
    assert profile["email"] == "admin@example.com"
    assert profile["role_name"] == "Employee"
    assert profile["permissions"] == ["write.attendance.local"]
    assert profile["privacy_notice_accepted"] is False


def test_login_locks_after_five_failures(client):
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    res = login(client)
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"email": "admin@example.com", "password": "wrong"}, 401),
        ({"email": "nobody@example.com", "password": "x"}, 401),
        ({"email": "admin@example.com"}, 400),
        ({"email": "bad", "password": "x"}, 400),
        ([1, 2], 400),
    ],
)
def test_login_failures(client, payload, status):
    res = client.post("/session", json=payload)
    assert res.status_code == status
    assert_envelope(res.json(), False)


def test_login_invalid_json(client):
    res = client.post("/session", content="{oops", headers={"Content-Type": "application/json"})
    assert res.status_code == 400
    assert_envelope(res.json(), False)


def test_protected_routes_require_bearer_token(client):
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer junk"}):
        res = client.get("/employee", headers=headers)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHENTICATED"


def test_register_then_list(client):
    headers = auth(client)
    res = client.post(
        "/employee",
        headers=headers,
        json={"name": "Ana", "email": "ana@example.com", "password": "pw", "role_id": 2},
    )
    assert res.status_code == 201
    employee = res.json()["data"]["employee"]
    assert employee["subsidiary_id"] == 1 and "password_hash" not in employee

    listed = client.get("/employee", headers=headers)
    assert listed.status_code == 200
    emails = [e["email"] for e in listed.json()["data"]["employees"]]
    assert emails == ["admin@example.com", "ana@example.com"]
    assert login(client, "ana@example.com", "pw").status_code == 200


def test_register_conflict_and_validation(client):
    headers = auth(client)
    dup = {"name": "A", "email": "admin@example.com", "password": "pw", "role_id": 1}
    assert client.post("/employee", headers=headers, json=dup).status_code == 409
    bad = {**dup, "email": "new@example.com", "role_id": "x"}
    assert client.post("/employee", headers=headers, json=bad).status_code == 400


def test_list_filter_by_subsidiary(client):
    headers = auth(client)
    assert client.get("/employee?subsidiary_id=2", headers=headers).json()["data"] == {"employees": []}
    for bad in ("abc", "0", "-1", "1.5"):
        res = client.get(f"/employee?subsidiary_id={bad}", headers=headers)
        assert res.status_code == 400, bad


def test_logout_revokes_token(client):
    headers = auth(client)
    res = client.delete("/session", headers=headers)
    assert res.status_code == 200
    assert_envelope(res.json(), True)
    assert "data" not in res.json()
    assert client.get("/employee", headers=headers).status_code == 401


def test_unknown_route_uses_envelope(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert_envelope(res.json(), False)


def test_create_app_requires_secret():
    with pytest.raises(RuntimeError):
        create_app({})


def test_create_app_rejects_short_secret(app_env):
    with pytest.raises(RuntimeError, match="32"):
        create_app({**app_env, "JWT_SECRET": "short"})


def test_create_app_requires_postgres(app_env):
    for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        with pytest.raises(RuntimeError, match="POSTGRES"):
            create_app({k: v for k, v in app_env.items() if k != key})


def register_employee(client, headers, email, subsidiary_id=None):
    body = {"name": "N", "email": email, "password": "p", "role_id": 2}
    if subsidiary_id is not None:
        body["subsidiary_id"] = subsidiary_id
    return client.post("/employee", json=body, headers=headers).json()["data"]["employee"]["id"]


def test_record_attendance_flow(client, pg_pool):
    # No endpoint assigns rooms yet, so put the employees in room 1 directly.
    headers = auth(client)
    put_in_room(pg_pool, "admin@example.com", 1)
    a = register_employee(client, headers, "a@x.com")
    b = register_employee(client, headers, "b@x.com")
    other = register_employee(client, headers, "o@x.com", subsidiary_id=2)
    put_in_room(pg_pool, "a@x.com", 1)
    put_in_room(pg_pool, "b@x.com", 1)
    payload = {"records": [{"employee_id": a, "status": "ON_TIME"}, {"employee_id": b, "status": "ABSENT"}]}

    res = client.post("/attendance", json=payload, headers=headers)
    assert res.status_code == 201
    assert_envelope(res.json(), True)
    items = res.json()["data"]["attendances"]
    assert [i["status"] for i in items] == ["ON_TIME", "ABSENT"]

    again = client.post("/attendance", json=payload, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONFLICT"

    forbidden = client.post(
        "/attendance", json={"records": [{"employee_id": other, "status": "LATE"}]}, headers=headers
    )
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"

    missing = client.post(
        "/attendance", json={"records": [{"employee_id": 999, "status": "LATE"}]}, headers=headers
    )
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"records": []},
        {"records": "x"},
        {"records": [1]},
        {"records": [{"employee_id": 1, "status": "EXITED"}]},
        {"records": [{"employee_id": 1, "status": "NOPE"}]},
        {"records": [{"employee_id": "1", "status": "LATE"}]},
        {"records": [{"employee_id": 1, "status": "LATE"}, {"employee_id": 1, "status": "LATE"}]},
    ],
)
def test_record_attendance_invalid_body(client, payload):
    res = client.post("/attendance", json=payload, headers=auth(client))
    assert res.status_code == 400
    assert_envelope(res.json(), False)


def test_record_attendance_requires_auth(client):
    res = client.post("/attendance", json={"records": []})
    assert res.status_code == 401


def test_list_attendance_is_exhaustive_for_callers_room(client, pg_pool):
    headers = auth(client)
    put_in_room(pg_pool, "admin@example.com", 1)
    a = register_employee(client, headers, "a@x.com")
    b = register_employee(client, headers, "b@x.com")
    register_employee(client, headers, "o@x.com")
    put_in_room(pg_pool, "a@x.com", 1)
    put_in_room(pg_pool, "b@x.com", 1)
    put_in_room(pg_pool, "o@x.com", 2)
    client.post(
        "/attendance", json={"records": [{"employee_id": a, "status": "LATE"}]}, headers=headers
    )
    res = client.get("/attendance", headers=headers)
    assert res.status_code == 200
    assert_envelope(res.json(), True)
    rows = {r["employee"]["id"]: r for r in res.json()["data"]["employees"]}
    assert set(rows) == {1, a, b}
    assert [x["status"] for x in rows[a]["attendances"]] == ["LATE"]
    assert rows[b]["attendances"] == []


def test_list_attendance_requires_auth(client):
    assert client.get("/attendance").status_code == 401


def test_list_attendance_caller_without_room_is_forbidden(client):
    res = client.get("/attendance", headers=auth(client))
    assert res.status_code == 403


def test_create_capacitation(client):
    res = client.post(
        "/capacitation",
        json={"name": "Fire safety", "description": "Annual course"},
        headers=auth(client),
    )
    body = res.json()
    assert res.status_code == 201
    assert_envelope(body, True)
    data = body["data"]["capacitation"]
    assert data["id"] == 1
    assert (data["name"], data["description"]) == ("Fire safety", "Annual course")
    assert data["created_by"] and data["created_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "x"},
        {"description": "x"},
        {"name": " ", "description": "x"},
        {"name": "x" * 101, "description": "x"},
        {"name": "x", "description": "y" * 256},
    ],
)
def test_create_capacitation_invalid_body(client, payload):
    res = client.post("/capacitation", json=payload, headers=auth(client))
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_REQUEST"


def test_create_capacitation_requires_auth(client):
    res = client.post("/capacitation", json={"name": "x", "description": "y"})
    assert res.status_code == 401


def _create_capacitation(client):
    client.post(
        "/capacitation",
        json={"name": "Fire safety", "description": "Annual course"},
        headers=auth(client),
    )


def test_assign_capacitation(client):
    _create_capacitation(client)
    me = client.get("/employee", headers=auth(client)).json()["data"]["employees"][0]["id"]
    res = client.post(
        "/capacitation/assignment",
        json={"capacitation_id": 1, "employee_id": me},
        headers=auth(client),
    )
    body = res.json()
    assert res.status_code == 201
    assert_envelope(body, True)
    data = body["data"]["assignment"]
    assert (data["employee_id"], data["capacitation_id"], data["is_pending"]) == (me, 1, True)
    assert data["assigned_by"] == me and data["assigned_at"]


def test_assign_capacitation_twice_conflicts(client):
    _create_capacitation(client)
    me = client.get("/employee", headers=auth(client)).json()["data"]["employees"][0]["id"]
    payload = {"capacitation_id": 1, "employee_id": me}
    client.post("/capacitation/assignment", json=payload, headers=auth(client))
    res = client.post("/capacitation/assignment", json=payload, headers=auth(client))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "CONFLICT"


def test_assign_unknown_capacitation_or_employee(client):
    _create_capacitation(client)
    me = client.get("/employee", headers=auth(client)).json()["data"]["employees"][0]["id"]
    for payload in ({"capacitation_id": 99, "employee_id": me}, {"capacitation_id": 1, "employee_id": 999}):
        res = client.post("/capacitation/assignment", json=payload, headers=auth(client))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [{}, {"capacitation_id": 1}, {"employee_id": 1}, {"capacitation_id": 0, "employee_id": 1}, {"capacitation_id": "1", "employee_id": 1}],
)
def test_assign_capacitation_invalid_body(client, payload):
    res = client.post("/capacitation/assignment", json=payload, headers=auth(client))
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_REQUEST"


def test_assign_capacitation_requires_auth(client):
    res = client.post("/capacitation/assignment", json={"capacitation_id": 1, "employee_id": 1})
    assert res.status_code == 401



def test_get_session_returns_profile(client):
    res = client.get("/session", headers=auth(client))
    body = res.json()
    assert res.status_code == 200
    assert_envelope(body, True)
    assert body["data"] == login(client).json()["data"]["profile"]


def test_get_session_without_token_is_401(client):
    assert client.get("/session").status_code == 401


def test_change_password_revokes_token_and_new_password_logs_in(client):
    headers = auth(client)
    res = client.put(
        "/employee/me/password",
        headers=headers,
        json={"current_password": "admin-pass", "new_password": "brand-new-pass"},
    )
    assert res.status_code == 200
    assert_envelope(res.json(), True)
    assert client.get("/session", headers=headers).status_code == 401
    assert login(client, password="admin-pass").status_code == 401
    assert login(client, password="brand-new-pass").status_code == 200


def test_change_password_wrong_current_or_short_new(client):
    headers = auth(client)
    wrong = client.put(
        "/employee/me/password",
        headers=headers,
        json={"current_password": "nope-nope", "new_password": "brand-new-pass"},
    )
    assert wrong.status_code == 401
    short = client.put(
        "/employee/me/password",
        headers=headers,
        json={"current_password": "admin-pass", "new_password": "short"},
    )
    assert short.status_code == 400
    assert client.get("/session", headers=headers).status_code == 200
