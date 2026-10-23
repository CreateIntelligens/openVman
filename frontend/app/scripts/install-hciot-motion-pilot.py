"""Install a protected pilot character through the existing management API."""

import gzip
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import urllib.request
import uuid

from pipeline.bundle import decrypt_inner, encrypt_inner, load_bundle_key


CHARACTER_ID = "hciot-motion"
LABEL = "HCIOT 醫院動作試用"
OWNER_PROJECT = "proj-9c042e94e0"
ALLOWED_PROJECTS = {OWNER_PROJECT, "proj-b85afb8bb6"}
SOURCE = Path("/data/avatar/0624/motion-lab/hciot-v1")
TARGET = Path("/data/avatar") / CHARACTER_ID
JOB = Path("/data/avatar-jobs/hciot-vman-install")
BASE_URL = "https://10.9.0.32:8787"


class ApiResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return json.loads(self.body)

    def raise_for_status(self):
        # urllib raises HTTPError before constructing this response.
        pass


class ApiSession:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        )

    def request(self, method, url, *, payload=None, data=None, files=None):
        headers = {"Origin": BASE_URL}
        body = None
        if files:
            boundary = uuid.uuid4().hex
            parts = []
            for name, value in data.items():
                parts.append((f'--{boundary}\r\nContent-Disposition: form-data; '
                              f'name="{name}"\r\n\r\n{value}\r\n').encode())
            for name, (filename, handle, mime) in files.items():
                parts.extend([(f'--{boundary}\r\nContent-Disposition: form-data; '
                               f'name="{name}"; filename="{filename}"\r\n'
                               f'Content-Type: {mime}\r\n\r\n').encode(),
                              handle.read(), b'\r\n'])
            parts.append(f'--{boundary}--\r\n'.encode())
            body = b''.join(parts)
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        elif payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with self.opener.open(request, timeout=120) as response:
            return ApiResponse(response.read())

    def get(self, url):
        return self.request("GET", url)

    def post(self, url, **options):
        return self.request("POST", url, **options)

    def put(self, url, **options):
        return self.request("PUT", url, **options)


def main():
    projects = list(dict.fromkeys(os.environ["MOTION_PILOT_PROJECT_IDS"].split(",")))
    if not projects or not set(projects) <= ALLOWED_PROJECTS:
        raise RuntimeError("僅能安裝到已核准的醫院試用專案")
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    if manifest["id"] != "hciot-v1" or manifest["frameCount"] != 800:
        raise RuntimeError("請先準備正確的 HCIOT 動作素材包")
    JOB.mkdir(parents=True, exist_ok=True)
    session = ApiSession()
    session.post(BASE_URL + "/api/v1/auth/admin-login", payload={
        "username": os.environ["MOTION_TEST_USERNAME"],
        "password": os.environ["MOTION_TEST_PASSWORD"],
    }).raise_for_status()
    response = session.get(BASE_URL + "/api/v1/avatar")
    response.raise_for_status()
    existing = next((item for item in response.json()["characters"]
                     if item["char_id"] == CHARACTER_ID), None)
    if existing and existing.get("owner_project_id") != OWNER_PROJECT:
        raise RuntimeError("同名人物不屬於元復醫院，停止安裝")
    created = existing is None
    if created:
        neutral = JOB / "neutral"
        neutral.mkdir(exist_ok=True)
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(SOURCE / "01.webm"), "-t", "8", "-map", "0:v:0",
            "-c:v", "copy", "-an", str(neutral / "01.webm"),
        ], check=True)
        frames = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames", "-of", "json",
            str(neutral / "01.webm"),
        ]))["streams"][0]["nb_read_frames"]
        if int(frames) != 200:
            raise RuntimeError("中立底片不是 200 幀，停止發布")
        key = load_bundle_key()
        outer = json.loads(gzip.decompress((SOURCE / "combined_data.json.gz").read_bytes()))
        inner = json.loads(decrypt_inner(key, outer["combined_data"]))
        inner.update(uid=f"vman_{uuid.uuid4()}", frame_num=200, rect=inner["rect"][:200])
        outer = {"json_data": outer["json_data"][:200], "combined_data": encrypt_inner(
            key, json.dumps(inner, separators=(",", ":")).encode(),
        )}
        with gzip.open(neutral / "combined_data.json.gz", "wt") as handle:
            json.dump(outer, handle, separators=(",", ":"))
        with (neutral / "01.webm").open("rb") as video, (neutral / "combined_data.json.gz").open("rb") as data:
            session.post(BASE_URL + "/api/v1/avatar", data={
                "char_id": CHARACTER_ID, "label": LABEL, "project_id": OWNER_PROJECT,
            }, files={"video": ("01.webm", video, "video/webm"),
                      "data": ("combined_data.json.gz", data, "application/gzip")}).raise_for_status()
    motion_parent = TARGET / "motions"
    motion_parent.mkdir(exist_ok=True)
    destination = motion_parent / "hciot-v1"
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix=".install-", dir=motion_parent) as tmp:
            bundle = Path(tmp) / "hciot-v1"
            shutil.copytree(SOURCE, bundle)
            os.replace(bundle, destination)
    if json.loads((destination / "manifest.json").read_text()) != manifest:
        raise RuntimeError("已安裝的動作包與來源不同，停止更新專案設定")
    changed = []
    for project_id in projects:
        path = f"/api/v1/projects/{project_id}"
        before = session.get(BASE_URL + path + "/policy")
        before.raise_for_status()
        policy = before.json()
        backup = JOB / f"{project_id}-policy-before.json"
        if not backup.exists():
            backup.write_text(json.dumps(policy, ensure_ascii=False, indent=2))
        session.post(BASE_URL + path + "/assignments", payload={
            "resource_type": "avatar_character", "resource_id": CHARACTER_ID,
        }).raise_for_status()
        updated = {name: value for name, value in policy.items()
                   if name not in {"project_id", "updated_by", "updated_at"}}
        updated["default_character_id"] = CHARACTER_ID
        if updated.get("allowed_characters") and CHARACTER_ID not in updated["allowed_characters"]:
            updated["allowed_characters"].append(CHARACTER_ID)
        session.put(BASE_URL + path + "/policy", payload=updated).raise_for_status()
        verify = session.get(BASE_URL + path + "/resources")
        verify.raise_for_status()
        if verify.json()["defaults"]["avatar_character"] != CHARACTER_ID:
            raise RuntimeError(f"{project_id} 的人物預設值驗證失敗")
        changed.append({"projectId": project_id, "beforeDefault": policy.get("default_character_id"),
                        "default": CHARACTER_ID})
    print(json.dumps({"characterId": CHARACTER_ID, "created": created,
                      "ownerProject": OWNER_PROJECT, "projects": changed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
