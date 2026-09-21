"""Tests for A2A Brain Skill invoking Backend internal facade."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
from threading import Thread
from unittest.mock import patch

import pytest

from tools.skill_manager import SkillManager

skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from a2a.main import a2a_broadcast_group, a2a_list_peers, a2a_send_task


def test_skill_manager_loads_a2a_skill():
    """Verify that SkillManager discovers and registers the a2a skill from brain/skills."""
    manager = SkillManager(str(skills_dir))
    manager.scan_and_load_skills()

    registered_skills = manager.list_skills()
    skill_ids = [s.manifest.id for s in registered_skills]
    assert "a2a" in skill_ids

    # Check tools exposed by a2a
    a2a_skill = next(s for s in registered_skills if s.manifest.id == "a2a")
    tool_names = [t.name for t in a2a_skill.manifest.tools]
    assert "a2a_list_peers" in tool_names
    assert "a2a_send_task" in tool_names
    assert "a2a_broadcast_group" in tool_names


@patch("urllib.request.urlopen")
def test_a2a_list_peers(mock_urlopen):
    fake_response = io.BytesIO(
        json.dumps({
            "peers": [
                {"agentId": "agent-1", "displayName": "OpenClaw", "state": "ONLINE"},
                {"agentId": "agent-2", "displayName": "Codex", "state": "ONLINE"},
            ],
            "total": 2,
            "enabled": True,
        }).encode("utf-8")
    )
    mock_urlopen.return_value.__enter__.return_value = fake_response

    result = a2a_list_peers({"state": "online"})
    assert "peers" in result
    assert result["total"] == 2
    assert result["peers"][0]["displayName"] == "OpenClaw"

    # Verify that the URL called was the internal facade
    called_req = mock_urlopen.call_args[0][0]
    assert "/api/v1/internal/a2a/peers?state=online" in called_req.full_url
    assert called_req.has_header("X-internal-token")


@patch("urllib.request.urlopen")
def test_a2a_send_task(mock_urlopen):
    fake_response = io.BytesIO(
        json.dumps({"success": True, "target": "agent-openclaw", "result": {"taskId": "task-abc", "status": "QUEUED"}}).encode("utf-8")
    )
    mock_urlopen.return_value.__enter__.return_value = fake_response

    result = a2a_send_task({
        "target_agent_id": "agent-openclaw",
        "message": "Analyze system load",
        "hop_count": 1,
    })
    assert result["success"] is True
    assert result["target"] == "agent-openclaw"

    called_req = mock_urlopen.call_args[0][0]
    assert "/api/v1/internal/a2a/tasks" in called_req.full_url
    assert called_req.has_header("X-internal-token")


@pytest.mark.parametrize("args, error", [
    ({}, "target_agent_id is required"),
    ({"target_agent_id": "peer"}, "message is required"),
    ({"target_agent_id": "  ", "message": "hello"},
     "target_agent_id is required"),
])
@patch("urllib.request.urlopen")
def test_a2a_send_task_validation(mock_urlopen, args, error):
    assert a2a_send_task(args) == {"error": error}
    mock_urlopen.assert_not_called()


@patch("urllib.request.urlopen")
def test_a2a_broadcast_group(mock_urlopen):
    fake_response = io.BytesIO(
        json.dumps({"success": True, "groupId": "team-circle-1", "result": {"groupMessageId": 99, "status": "BROADCASTED"}}).encode("utf-8")
    )
    mock_urlopen.return_value.__enter__.return_value = fake_response

    result = a2a_broadcast_group({
        "group_id": "team-circle-1",
        "message": "Attention squad!",
    })
    assert result["success"] is True
    assert result["groupId"] == "team-circle-1"

    called_req = mock_urlopen.call_args[0][0]
    assert "/api/v1/internal/a2a/groups/messages" in called_req.full_url
    assert called_req.has_header("X-internal-token")


@pytest.mark.parametrize("tool, args, field", [
    (a2a_send_task, {"target_agent_id": "peer", "message": "hello"},
     "target_agent_id"),
    (a2a_send_task, {"target_agent_id": "peer", "message": "hello"}, "message"),
    (a2a_send_task, {"target_agent_id": "peer", "message": "hello"}, "context_id"),
    (a2a_broadcast_group, {"group_id": "group", "message": "hello"}, "group_id"),
    (a2a_broadcast_group, {"group_id": "group", "message": "hello"}, "message"),
])
@pytest.mark.parametrize("value", [True, 1, ["peer"], {"peer": "id"}])
@patch("urllib.request.urlopen")
def test_a2a_rejects_non_string_fields(mock_urlopen, tool, args, field, value):
    assert tool({**args, field: value}) == {"error": f"{field} must be a string"}
    mock_urlopen.assert_not_called()


@pytest.mark.parametrize("hop_count", [True, False, -1, 11, 1.5, "1", None])
@patch("urllib.request.urlopen")
def test_send_task_rejects_invalid_hop_count(mock_urlopen, hop_count):
    result = a2a_send_task({
        "target_agent_id": "peer", "message": "hello", "hop_count": hop_count,
    })
    assert result == {"error": "hop_count must be an integer between 0 and 10"}
    mock_urlopen.assert_not_called()


@pytest.mark.parametrize("field, value", [
    ("target_agent_id", "x" * 257),
    ("context_id", "x" * 257),
    ("message", "中" * 349526),
])
@patch("urllib.request.urlopen")
def test_send_task_rejects_oversized_fields(mock_urlopen, field, value):
    result = a2a_send_task({
        "target_agent_id": "peer", "message": "hello", field: value,
    })
    assert result == {"error": f"{field} is too long"}
    mock_urlopen.assert_not_called()


@pytest.mark.parametrize("context_id, expected_context", [
    (None, None),
    ("", None),
    ("   ", None),
    (" context ", "context"),
])
@pytest.mark.parametrize("hop_count", [0, 10])
@patch("urllib.request.urlopen")
def test_send_task_normalizes_valid_payload(
    mock_urlopen, context_id, expected_context, hop_count,
) -> None:
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"success":true}')
    result = a2a_send_task({
        "target_agent_id": " peer ", "message": " hello ",
        "context_id": context_id, "hop_count": hop_count,
    })
    assert result == {"success": True}
    request = mock_urlopen.call_args.args[0]
    assert json.loads(request.data) == {
        "target_agent_id": "peer", "message": "hello",
        "context_id": expected_context,
        "hop_count": hop_count,
    }


@patch("urllib.request.urlopen")
def test_send_task_accepts_id_and_utf8_message_limits(mock_urlopen):
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"success":true}')
    message = "中" * 349525 + "a"
    assert len(message.encode("utf-8")) == 1048576
    assert a2a_send_task({
        "target_agent_id": "x" * 256, "context_id": "y" * 256,
        "message": message,
    }) == {"success": True}
    mock_urlopen.assert_called_once()


def test_send_task_real_http_transport(monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append({
                "path": self.path,
                "token": self.headers.get("X-Internal-Token"),
                "payload": json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                ),
            })
            body = b'{"success":true,"result":{"taskId":"local-test"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "BACKEND_INTERNAL_URL", f"http://127.0.0.1:{server.server_port}",
    )
    monkeypatch.setenv("GATEWAY_INTERNAL_TOKEN", "local-test-token")
    try:
        result = a2a_send_task({
            "target_agent_id": " peer ", "message": " hello ",
            "context_id": " context ", "hop_count": 0,
        })
        assert result == {"success": True, "result": {"taskId": "local-test"}}
        assert received == [{
            "path": "/api/v1/internal/a2a/tasks", "token": "local-test-token",
            "payload": {"target_agent_id": "peer", "message": "hello",
                        "context_id": "context", "hop_count": 0},
        }]
        assert "error" in a2a_send_task({
            "target_agent_id": "peer", "message": "hello", "hop_count": True,
        })
        assert len(received) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
