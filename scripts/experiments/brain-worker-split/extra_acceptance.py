"""Management writes must be visible through independent chat connections."""

from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
from pathlib import Path


async def verify_settings(client, headers, *, backend, admin, chat, project, internal_headers):
    url = backend + "/api/v1/knowledge/settings"
    previous = await client.get(url, headers=headers, params={"project_id": project})
    previous.raise_for_status()
    original = previous.json()
    try:
        response = await client.put(url, headers=headers, json={"project_id": project, "language_routes": ["zh", "en"], "reply_seconds": 17})
        response.raise_for_status()
        for base in (admin, chat):
            for _ in range(4):
                observed = await client.get(base + "/brain/knowledge/settings", params={"project_id": project}, headers={**internal_headers, "Connection": "close"})
                observed.raise_for_status()
                settings = observed.json()
                assert settings["language_routes"] == ["zh", "en"] and settings["reply_seconds"] == 17, settings
        denied = await client.put(chat + "/brain/knowledge/settings", headers=internal_headers, json={"project_id": project, "language_routes": ["zh"]})
        assert denied.status_code in (404, 405), denied.text
    finally:
        restored = await client.put(url, headers=headers, json={"project_id": project, "language_routes": original["language_routes"], "reply_seconds": original["reply_seconds"]})
        restored.raise_for_status()
    return "KB settings updated through Backend and read consistently from admin/chat; chat PUT rejected"


async def verify_import_during_chat(client, headers, *, backend, project, request_chat):
    import csv

    content = io.StringIO()
    writer = csv.writer(content)
    writer.writerow(["問題", "答案"])
    for index in range(80):
        writer.writerow([f"虛構隔離測試問題{index}", f"這是編號{index}的合成資料，僅供隔離驗收，不含任何真實業務資訊。"])
    name = "synthetic-qa-" + uuid.uuid4().hex[:10] + ".csv"
    response = await client.post(backend + "/api/v1/knowledge/raw/upload", headers=headers, data={"project_id": project, "target_dir": "raw"}, files=[("files", (name, content.getvalue().encode("utf-8-sig"), "text/csv"))])
    response.raise_for_status()
    response = await client.post(backend + "/api/v1/knowledge/raw/commit", headers=headers, json={"project_id": project, "paths": ["raw/" + name], "normalize": False})
    response.raise_for_status()
    assert response.json().get("status") == "started", response.text
    states = []
    conversation = None
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            status = await client.get(backend + "/api/v1/knowledge/raw/commit/status", headers=headers, params={"project_id": project})
            status.raise_for_status()
            body = status.json()
            state = body.get("state")
            states.append(state)
            assert state not in ("idle", "failed"), body
            if state == "running" and conversation is None:
                conversation = asyncio.create_task(request_chat(client, headers))
            if state == "done":
                assert body.get("committed") and not body.get("skipped"), body
                break
            await asyncio.sleep(.05)
        else:
            raise RuntimeError("synthetic QA import did not complete in 120s")
        assert conversation is not None, "import finished before a running state was observed; overlap unverified"
        result = await conversation
        assert result["ok"], result
        return {"check": "QA CSV imported while Backend chat ran successfully; admin progress never became idle", "observed_states": sorted(set(states)), "chat_first_sentence": result["first_sentence"]}
    finally:
        if conversation is not None and not conversation.done():
            conversation.cancel()
            await asyncio.gather(conversation, return_exceptions=True)


async def verify_enrich_history(client, headers, *, backend, project, internal_headers):
    session = "worker-enrich-" + uuid.uuid4().hex
    marker = "synthetic-enriched-" + uuid.uuid4().hex
    response = await client.post(backend + "/api/v1/internal/enrich", headers=internal_headers, json={"project_id": project, "session_id": session, "enriched_context": [{"type": "test", "content": marker}]})
    response.raise_for_status()
    assert response.json().get("stored_count") == 1, response.text
    for _ in range(8):
        observed = await client.get(backend + "/api/v1/chat/history", headers={**headers, "Connection": "close"}, params={"project_id": project, "session_id": session})
        observed.raise_for_status()
        assert marker in json.dumps(observed.json(), ensure_ascii=False), observed.text
    return "Backend internal enrich persisted and was visible in eight independent chat history connections"


async def verify_backup(client, headers, *, backend, project, expected_session):
    response = await client.post(backend + "/api/v1/backups/sessions", headers=headers, json={"dry_run": False})
    response.raise_for_status()
    backup = response.json()
    assert backup.get("total_messages", 0) >= 2, backup
    root = Path("/brain-data/backups/sessions") / backup["backup_id"] / project
    sessions = [json.loads(line) for path in root.glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert any(session.get("session_id") == expected_session and len(session.get("messages", [])) >= 2 for session in sessions), (backup, sessions[:1])
    return "Backup triggered through Backend exported the accepted chat session and messages from shared SQLite"


async def verify_metrics(client, headers, *, chat, internal_headers, request_chat):
    async def count():
        response = await client.get(chat + "/brain/metrics", headers={**internal_headers, "Connection": "close"})
        response.raise_for_status()
        return sum(value for name, value in response.json()["counters"].items() if name.startswith("http_requests_total|") and "path=/brain/chat/stream," in name)

    before = await count()
    results = await asyncio.gather(*(request_chat(client, headers) for _ in range(8)))
    assert all(result["ok"] for result in results), results
    observed = [await count() for _ in range(8)]
    assert all(value >= before + 8 for value in observed), {"before": before, "after": observed}
    return {"check": "Eight metric reads after eight independent chats included all new chat request counts", "before": before, "observed": observed}


async def verify_project_skill(client, headers, *, backend, project):
    identifier = "worker_project_" + uuid.uuid4().hex[:10]
    query = {"scope": "project", "project_id": project}
    response = await client.post(
        backend + "/api/v1/skills", headers=headers,
        json={"skill_id": identifier, "name": "Synthetic project skill",
              "description": "Disposable project scoping acceptance",
              "scope": "project", "project_id": project},
    )
    response.raise_for_status()
    try:
        response = await client.get(
            backend + "/api/v1/tools", headers=headers,
            params={"project_id": project},
        )
        response.raise_for_status()
        assert any(skill["id"] == identifier and skill["project_id"] == project
                   for skill in response.json()["skills"]), response.text
        response = await client.get(
            backend + f"/api/v1/skills/{identifier}/files",
            headers=headers, params=query,
        )
        response.raise_for_status()
        assert "main.py" in response.json()["files"], response.text
        response = await client.patch(
            backend + f"/api/v1/skills/{identifier}/toggle",
            headers=headers, params=query,
        )
        response.raise_for_status()
        assert response.json()["enabled"] is False, response.text
        response = await client.get(
            backend + "/api/v1/tools", headers=headers,
            params={"project_id": project},
        )
        response.raise_for_status()
        assert not any(identifier in tool["name"]
                       for tool in response.json()["skill_tools"]), response.text
    finally:
        removed = await client.delete(
            backend + f"/api/v1/skills/{identifier}",
            headers=headers, params=query,
        )
        removed.raise_for_status()
    return "Project skill create/list/files/toggle/delete preserved requested project scope"
