"""Tests for A2A Brain Skill invoking Backend internal facade."""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tools.skill_manager import SkillManager
import sys

skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from a2a.main import a2a_list_peers, a2a_send_task, a2a_broadcast_group


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


def test_a2a_send_task_validation():
    result = a2a_send_task({})
    assert "error" in result
    assert "Missing required fields" in result["error"]


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
