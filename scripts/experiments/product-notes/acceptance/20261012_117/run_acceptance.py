"""Package current source over stdin and run read-only production generation.

No LLM calls happen during --help or --self-test. Run generation only after the
question set is frozen and its exact SHA-256 is supplied by the operator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PREFIX = "PRODUCT_ACCEPTANCE_EVENT "
CONTAINER = "openvman-api-1"
EXCLUDED_PARTS = {".venv", "__pycache__", "data", "node_modules", ".git"}
BOOTSTRAP = r'''
import io,json,logging,pathlib,sys,tarfile,tempfile
sys.dont_write_bytecode=True
logging.disable(logging.CRITICAL)
base=pathlib.Path('/tmp/private')
base.mkdir(exist_ok=True)
root=pathlib.Path(tempfile.mkdtemp(prefix='accept117-',dir=base))
try:
    with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as tar:
        for member in tar.getmembers():
            target=(root/member.name).resolve()
            if not target.is_relative_to(root) or not member.isfile():
                raise RuntimeError('Unsafe bundle entry')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
    data=json.loads((root/'payload.json').read_text())
    source=root/'acceptance/runtime.py'
    exec(compile(source.read_text(),str(source),'exec'),{
        '__name__':'__acceptance_runtime__','__file__':str(source),
        'DATA':data,'PRIVATE_ROOT':root,
    })
except BaseException as exc:
    print('PRODUCT_ACCEPTANCE_EVENT '+json.dumps({
        'type':'process_failure','class':type(exc).__name__,
        'message':'Container process stopped; see sanitized failure event',
    }),flush=True)
    sys.exit(1)
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")


def collect_source():
    files = {}
    for directory in ("brain/api", "contracts"):
        for path in sorted((REPO / directory).rglob("*")):
            relative = path.relative_to(REPO)
            if (path.is_file() and not path.is_symlink()
                    and path.suffix in {".py", ".ini", ".json"}
                    and not EXCLUDED_PARTS.intersection(relative.parts)
                    and not any(word in path.name.lower() for word in (
                        "credential", "auth.json", "secret", ".env",
                    ))):
                files[str(relative)] = path.read_bytes()
    files["acceptance/runtime.py"] = (HERE / "runtime.py").read_bytes()
    hashes = {path: digest(raw) for path, raw in files.items()}
    source_sha = digest(json.dumps(hashes, sort_keys=True,
                                   separators=(",", ":")).encode())
    return files, hashes, source_sha


def checkout_head():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
    ).strip()


def question_payload(raw, supplied_sha, full, probe):
    if digest(raw) != supplied_sha:
        raise ValueError("questions freeze SHA-256 mismatch")
    document = json.loads(raw)
    questions = document["questions"]
    # Oracle stays on the host; only these two fields enter generation.
    clean = [{"id": q["id"], "question": q["question"]} for q in questions]
    if len({q["id"] for q in clean}) != len(clean):
        raise ValueError("Duplicate question IDs")
    if any(not isinstance(q["id"], str) or not isinstance(q["question"], str)
           or not q["question"].strip() for q in clean):
        raise ValueError("Invalid question payload")
    if full and len(clean) != 20:
        raise ValueError("Full acceptance requires 20 frozen questions")
    return [(rep, q) for rep in range(1, 4) for q in clean] if full else [
        (1, q) for q in clean[:probe]
    ]


def make_bundle(files, data):
    buffer = io.BytesIO()
    entries = {**files, "payload.json": json.dumps(
        data, ensure_ascii=False, separators=(",", ":")
    ).encode()}
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, raw in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(raw))
    return buffer.getvalue()


def mirror_check(label):
    check = subprocess.run(
        ["python3", "scripts/project_mirror.py", "check"], cwd=REPO,
        capture_output=True, text=True,
    )
    # Exit 1 is preserved, not rewritten as successful parity.
    item = {"command": "python3 scripts/project_mirror.py check",
            "exit_code": check.returncode,
            "stdout": check.stdout, "stderr": check.stderr}
    write_json("mirror_" + label + ".json", item)
    return item


def require_new_run(label, root=HERE):
    # Reject reuse before even the mirror evidence is overwritten.
    names = [
        f"{label}_checkpoint.jsonl", f"{label}_process.json",
        f"{label}_integrity.full.json", f"mirror_{label}_before.json",
        f"mirror_{label}_after.json",
        "results.json" if label == "full" else f"{label}_results.json",
    ]
    if any((root / name).exists() for name in names):
        raise ValueError("Run artifacts exist; use an explicit new run label")


def run_container(bundle, mode):
    checkpoint = HERE / f"{mode}_checkpoint.jsonl"
    if checkpoint.exists():
        raise ValueError("Checkpoint exists; explicit new artifact name required")
    process = subprocess.Popen(
        ["docker", "exec", "-i", "-w", "/app", CONTAINER,
         "python3", "-B", "-c", BOOTSTRAP],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stderr_digest = hashlib.sha256()
    stderr_bytes = [0]

    def drain_stderr():
        while chunk := process.stderr.read(65536):
            stderr_digest.update(chunk)
            stderr_bytes[0] += len(chunk)

    def send_bundle():
        try:
            process.stdin.write(bundle)
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()

    reader = threading.Thread(target=drain_stderr)
    writer = threading.Thread(target=send_bundle)
    reader.start()
    writer.start()
    result = None
    non_event_lines = 0
    with checkpoint.open("x", encoding="utf-8") as journal:
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace")
            if not line.startswith(PREFIX):
                non_event_lines += 1
                continue
            event = json.loads(line[len(PREFIX):])
            journal.write(json.dumps(event, ensure_ascii=False) + "\n")
            journal.flush()
            if event["type"] == "result":
                result = event["data"]
                full = result["integrity"].pop("full")
                write_json(f"{mode}_integrity.full.json", full)
                write_json("results.json" if mode == "full"
                           else f"{mode}_results.json", result)
            print(PREFIX + json.dumps({"type": event["type"],
                                       "label": event.get("label", "")}),
                  flush=True)
    code = process.wait()
    writer.join()
    reader.join()
    write_json(f"{mode}_process.json", {
        "exit_code": code, "stderr_bytes": stderr_bytes[0],
        "stderr_sha256": stderr_digest.hexdigest(),
        "non_event_lines_suppressed": non_event_lines,
    })
    if code or result is None or result["status"] != "completed":
        raise RuntimeError("Acceptance failed; sanitized checkpoints retained; no retry")
    if result["integrity"]["changed"]:
        raise RuntimeError("Workspace/LanceDB changed")
    return result


def self_test():
    spec = importlib.util.spec_from_file_location("acceptance_runtime", HERE / "runtime.py")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    raw = json.dumps({"questions": [
        {"id": "Q01", "question": "測試產品", "expected_answer": "ORACLE"},
    ]}).encode()
    schedule = question_payload(raw, digest(raw), False, 1)
    assert schedule == [(1, {"id": "Q01", "question": "測試產品"})]
    assert "ORACLE" not in json.dumps(schedule)
    calls = []
    recorder = runtime.Recorder()

    def prepare(envelope, **kwargs):
        assert envelope.context.metadata == {}
        assert envelope.context.message_type == "user"
        assert kwargs["reply_mode"] == "fast"
        calls.append("prepare")
        return SimpleNamespace(route={"skip_tools": False}, turn_decision=None,
                               input_language="zh", session_id="fixture",
                               prior_messages=[], reply_mode="fast")

    def execute(context):
        calls.append("execute")
        return SimpleNamespace(reply="完整回答", tool_steps=[])

    def finalize(context, reply, **kwargs):
        calls.append("finalize")
        assert kwargs["persist"] is False
        return {"reply": reply}

    service = SimpleNamespace(prepare_generation=prepare, execute_generation=execute,
                              finalize_generation=finalize)
    row = runtime.generate_one(schedule[0][1], 1, recorder, service,
                               SimpleNamespace, SimpleNamespace)
    assert calls == ["prepare", "execute", "finalize"]
    assert row["answer"] == "完整回答"
    assert "decision_debug" in row and row["calls"] == []
    fake_reply = SimpleNamespace(content="產品回答", model="fixture-model",
                                 tool_calls=[], usage=None)
    def generate_chat_turn(messages, **kwargs):
        return fake_reply
    wrapped = recorder.generate_wrapper(generate_chat_turn)
    wrapped([{"role": "system", "content": "原樣正式提示"},
             {"role": "user", "content": "不記錄prompt payload"}], max_tokens=123)
    assert recorder.calls[-1]["max_tokens"] == 123
    assert recorder.calls[-1]["content"] == "產品回答"
    assert "不記錄prompt payload" not in json.dumps(recorder.calls)
    try:
        runtime.guard_writes("open", ("/data/projects/test/file", "w", 0))
    except RuntimeError:
        pass
    else:
        raise AssertionError("Write guard fixture failed")
    try:
        runtime.ReadOnlyProxy(SimpleNamespace()).add([])
    except RuntimeError:
        pass
    else:
        raise AssertionError("Native DB guard fixture failed")
    assert runtime.plain({"api_key": "private", "model": "fixture"}) == {"model": "fixture"}
    assert "https://" not in runtime.safe_error(ValueError("https://private/x?key=sk-secret"))["message"]
    files, hashes, source_sha = collect_source()
    assert "brain/api/core/chat_service.py" in files
    assert "contracts/two-md-endpoints.json" in files
    assert all(not EXCLUDED_PARTS.intersection(Path(p).parts) for p in files)
    assert len(source_sha) == 64 and len(hashes) == len(files)
    bundle = make_bundle(files, {"schedule": schedule})
    with tarfile.open(fileobj=io.BytesIO(bundle)) as archive:
        assert all(m.isfile() and not Path(m.name).is_absolute()
                   and ".." not in Path(m.name).parts for m in archive.getmembers())
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        require_new_run("full", root)
        prior = root / "mirror_full_before.json"
        prior.write_text("preserved evidence")
        try:
            require_new_run("full", root)
        except ValueError:
            pass
        else:
            raise AssertionError("Existing run evidence must block reuse")
        assert prior.read_text() == "preserved evidence"
        require_new_run("new_run", root)
    print("Offline fixtures passed; no Docker or provider calls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probe", type=int, metavar="N")
    modes.add_argument("--full", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    parser.add_argument("--questions-sha256")
    parser.add_argument("--questions-frozen-at")
    parser.add_argument("--run-label", help="Unique checkpoint label for an explicit new run")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.questions_sha256:
        parser.error("Generation requires the explicitly confirmed questions SHA-256")
    if args.probe is not None and not 1 <= args.probe <= 20:
        parser.error("--probe must be between 1 and 20")
    raw = (HERE / "questions.json").read_bytes()
    schedule = question_payload(raw, args.questions_sha256, args.full, args.probe)
    document = json.loads(raw)
    freeze_path = HERE / "question_validation.json"
    freeze = json.loads(freeze_path.read_text()) if freeze_path.exists() else {}
    frozen_at = (args.questions_frozen_at or document.get("frozen_at")
                 or document.get("frozen_at_utc") or freeze.get("frozen_at")
                 or freeze.get("frozen_at_utc"))
    if not frozen_at:
        parser.error("Need frozen_at in questions.json or --questions-frozen-at")
    parity = json.loads((HERE / "behavior_parity.json").read_text())
    if parity.get("resolved_metadata_equal") is not True:
        raise ValueError("Resolved production/dev behavior parity must be true")
    snapshot = json.loads((HERE / "source_snapshot.json").read_text())
    for path, expected in snapshot["hashes"].items():
        if digest(snapshot["files"][path].encode()) != expected:
            raise ValueError("Frozen source snapshot hash mismatch")
    commit = checkout_head()
    files, hashes, source_sha = collect_source()
    if checkout_head() != commit:
        raise RuntimeError("HEAD changed during source copy; freeze again before running")
    data = {
        "schedule": schedule, "snapshot_hashes": snapshot["hashes"],
        "behavior_parity": parity, "bundle_hashes": hashes,
        "bundle_sha256": source_sha, "questions_sha256": digest(raw),
        "questions_frozen_at": frozen_at,
        "checkout": {"commit": commit, "source_manifest": hashes,
                     "snapshot_at": datetime.now(timezone.utc).isoformat()},
    }
    label = args.run_label or ("full" if args.full else f"probe{args.probe}")
    if not label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in label):
        parser.error("Unsafe run label")
    require_new_run(label)
    mirror_check(label + "_before")
    try:
        _, current_hashes, _ = collect_source()
        if checkout_head() != commit or current_hashes != hashes:
            raise RuntimeError("Checkout changed before launch; freeze/copy again")
        if digest((HERE / "questions.json").read_bytes()) != digest(raw):
            raise RuntimeError("Questions changed before launch; freeze again")
        run_container(make_bundle(files, data), label)
    finally:
        mirror_check(label + "_after")


if __name__ == "__main__":
    main()
