"""What Brain actually receives, over real sockets.

TestClient 與 MagicMock 上游各自多解碼／不解碼一次，看不出「Backend 授權的路徑」
與「Brain 收到的路徑」是否相同（2026-11-18：%2574ools 這類雙重編碼在 TestClient
測試全過，dev 上卻能讀到沒授權的專案）。這裡用真的 uvicorn 跑 Backend 與一個
假 Brain，用 http.client 送出原樣的請求行，檢查假 Brain 收到的路徑與 query。
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn

from app.http_client import SharedAsyncClient
from tests.api.test_main import _authenticated_client, _load_main, _make_test_config

_PROJECT = "project-a"
# 一般帳號自己擁有的專案；_PROJECT 屬於 admin，一般帳號沒有任何授權。
_OWN = "own-project"
_DEFAULT_BODY = object()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Server:
    def __init__(self, app: Any) -> None:
        self.port = _free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, lifespan="off", log_level="warning", ws="none",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> _Server:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.01)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


class _StubBrain:
    """Records the path, query, headers and body every request reaches Brain with."""

    def __init__(self) -> None:
        self.received: list[tuple[str, str, str]] = []
        self.headers: list[dict[str, str]] = []
        self.bodies: list[bytes] = []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        self.received.append(
            (scope["method"], scope["path"], scope["query_string"].decode("latin-1")),
        )
        self.headers.append(
            {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]},
        )
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        self.bodies.append(body)
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": b"{}"})


@pytest.fixture()
def wire(monkeypatch) -> Iterator[tuple[_StubBrain, Any]]:
    from app.auth.models import ResourceType, ResourceVisibility
    from app.auth.runtime import get_auth_runtime
    import app.brain_proxy as brain_proxy

    module, _ = _load_main(monkeypatch)
    _, admin_token = _authenticated_client(module)
    _, user_token = _authenticated_client(module, admin=False)
    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("test-admin")
    user = runtime.users.get_by_username("test-user")
    runtime.resources.register(
        resource_type=ResourceType.PROJECT, resource_id=_PROJECT,
        owner_user_id=admin.id, visibility=ResourceVisibility.PRIVATE,
    )
    runtime.resources.register(
        resource_type=ResourceType.PROJECT, resource_id=_OWN,
        owner_user_id=user.id, visibility=ResourceVisibility.PRIVATE,
    )

    brain = _StubBrain()
    with _Server(brain) as brain_server:
        brain_url = f"http://127.0.0.1:{brain_server.port}"
        monkeypatch.setattr(
            brain_proxy, "get_tts_config",
            lambda: _make_test_config(
                brain_url=brain_url,
                resolved_brain_chat_url=brain_url,
                brain_proxy_max_body_bytes=1024 * 1024,
            ),
        )
        monkeypatch.setattr(brain_proxy, "_http", SharedAsyncClient())
        with _Server(module.app) as backend:

            def send(
                method: str,
                target: str,
                *,
                token: str | None = "admin",
                body: Any = _DEFAULT_BODY,
                content_type: str | None = "application/json",
                headers: dict[str, str] | None = None,
            ) -> int:
                connection = http.client.HTTPConnection("127.0.0.1", backend.port, timeout=10)
                headers = dict(headers or {})
                if content_type:
                    headers["Content-Type"] = content_type
                if token:
                    headers["Authorization"] = (
                        f"Bearer {admin_token if token == 'admin' else user_token}"
                    )
                if body is _DEFAULT_BODY:
                    body = json.dumps({}) if method in {"PUT", "POST", "PATCH"} else None
                elif isinstance(body, dict):
                    body = json.dumps(body)
                # http.client 不會正規化路徑，請求行照這裡給的原樣送出。
                connection.request(method, target, body=body, headers=headers)
                status = connection.getresponse().status
                connection.close()
                return status

            yield brain, send


@pytest.mark.parametrize(
    ("method", "target", "brain_path"),
    [
        # 雙重編碼：Backend 解一次得到 %73kills 等字串，授權規則都對不上；Brain 必須
        # 收到同一個字串，不能再解一次變成 skills／knowledge／backups。
        ("PUT", f"/api/v1/%2573kills/joke/files?scope=shared&project_id={_PROJECT}", "/brain/%73kills/joke/files"),
        ("GET", f"/api/v1/%256Bnowledge/documents?project_id={_PROJECT}", "/brain/%6Bnowledge/documents"),
        ("GET", "/api/v1/%2562ackups/sessions", "/brain/%62ackups/sessions"),
        ("POST", f"/api/v1/knowledge%252Fupload?project_id={_PROJECT}", "/brain/knowledge%2Fupload"),
        # 一般的中文、空白、% 與 # 照樣以字面送到 Brain。
        ("GET", f"/api/v1/sessions/%E5%B0%8F%E6%98%8E%20a?project_id={_PROJECT}", "/brain/sessions/小明 a"),
        ("GET", f"/api/v1/sessions/a%25b?project_id={_PROJECT}", "/brain/sessions/a%b"),
        ("DELETE", f"/api/v1/sessions/abc%231?project_id={_PROJECT}", "/brain/sessions/abc#1"),
    ],
)
def test_brain_receives_exactly_the_path_the_backend_authorized(
    wire, method: str, target: str, brain_path: str,
) -> None:
    brain, send = wire

    send(method, target)

    assert [path for _, path, _ in brain.received] == [brain_path]


def test_double_encoded_route_cannot_read_an_ungranted_project(wire) -> None:
    brain, send = wire

    send("GET", f"/api/v1/%2574ools?project_id={_PROJECT}", token="user")
    status = send("GET", f"/api/v1/tools?project_id={_PROJECT}", token="user")

    assert status == 404
    assert [path for _, path, _ in brain.received] == ["/brain/%74ools"]


def test_encoded_dot_segments_stay_inside_the_skill_id(wire) -> None:
    brain, send = wire

    status = send("GET", f"/api/v1/skills/%252E%252E/files?scope=project&project_id={_PROJECT}")

    # 技能 ID「%2E%2E」不合法，Backend 直接擋，不會變成 Brain 上的 ..。
    assert status == 422
    assert brain.received == []


def test_query_reaches_brain_as_authorized(wire) -> None:
    brain, send = wire

    send("PATCH", f"/api/v1/skills/joke/toggle?scope=project&project_id={_PROJECT}")

    assert brain.received == [
        ("PATCH", "/brain/skills/joke/toggle", f"scope=project&project_id={_PROJECT}"),
    ]


def test_encoded_question_mark_does_not_make_a_path_public(wire) -> None:
    brain, send = wire

    # 不帶登入：/api/v1/health 是公開的，但 health%3F/... 不是。
    status = send("GET", "/api/v1/health%3F/x", token=None)
    traversal = send("GET", "/api/v1/health%3F/../skills/x", token=None)

    assert status == 401
    assert traversal in {401, 404}
    assert brain.received == []


# --- 授權的專案就是 Brain 用的專案 ---------------------------------------------
# 2026-11-18：Backend 只看 query 與有 JSON Content-Type 的 body；Brain 卻連沒有
# Content-Type 的 body、空的 project_id、X-Brain-Project 標頭都會拿來決定專案。


@pytest.mark.parametrize(
    ("method", "target", "kwargs"),
    [
        # 沒有 Content-Type 的 body 指向別的專案。
        (
            "PUT",
            f"/api/v1/knowledge/document?project_id={_OWN}",
            {"body": {"project_id": _PROJECT, "path": "SOUL.md", "content": "x"}, "content_type": None},
        ),
        # 空的 project_id：Brain 會改用預設專案。
        (
            "GET",
            "/api/v1/knowledge/document?project_id=&path=SOUL.md",
            {"body": {"project_id": _OWN}},
        ),
        # 重複的 project_id：Brain 取最後一個。
        ("GET", f"/api/v1/knowledge/document?project_id={_OWN}&project_id={_PROJECT}&path=SOUL.md", {}),
        # 對話信封會讀 message.project_id。
        (
            "POST",
            f"/api/v1/chat?project_id={_OWN}",
            {"body": {"message": {"content": "hi", "project_id": _PROJECT}}},
        ),
    ],
)
def test_requests_naming_another_project_are_refused(wire, method, target, kwargs) -> None:
    brain, send = wire

    status = send(method, target, token="user", **kwargs)

    assert status == 422
    assert brain.received == []


def test_forwarded_query_and_body_name_only_the_authorized_project(wire) -> None:
    brain, send = wire

    send(
        "PUT",
        f"/api/v1/knowledge/document?project_id={_OWN}",
        token="user",
        body={"path": "SOUL.md", "content": "x"},
        content_type=None,
    )

    assert brain.received == [("PUT", "/brain/knowledge/document", f"project_id={_OWN}")]
    assert json.loads(brain.bodies[0]) == {"path": "SOUL.md", "content": "x", "project_id": _OWN}


def test_client_brain_headers_do_not_reach_brain(wire) -> None:
    brain, send = wire

    send(
        "POST",
        f"/api/v1/chat?project_id={_OWN}",
        token="user",
        body={"message": "hi"},
        headers={"X-Brain-Project": _PROJECT, "X-Brain-Channel": "kiosk"},
    )

    assert len(brain.headers) == 1
    assert "x-brain-project" not in brain.headers[0]
    assert "x-brain-channel" not in brain.headers[0]
    assert brain.headers[0]["x-openvman-project-id"] == _OWN
    assert json.loads(brain.bodies[0])["project_id"] == _OWN


def test_oversized_body_is_refused_before_authorization_reads_it(wire) -> None:
    brain, send = wire
    huge = json.dumps({"project_id": _PROJECT, "content": "x" * (2 * 1024 * 1024)})

    status = send("PUT", f"/api/v1/knowledge/document?project_id={_PROJECT}", token="user", body=huge)

    # 以前先把整個 JSON 讀進來找 project_id（看不到的專案回 404），之後才檢查大小。
    assert status == 413
    assert brain.received == []


def test_public_health_is_read_only(wire) -> None:
    brain, send = wire

    status = send("POST", "/api/v1/health", token=None)

    assert status == 401
    assert brain.received == []
