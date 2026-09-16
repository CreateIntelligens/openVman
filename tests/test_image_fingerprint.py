"""Exercise image reuse against real Git histories and a fake registry."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.image_fingerprint import copy_sources, fingerprint

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/docker-publish.yml"
IMAGES = {
    "backend": ("backend", "backend/Dockerfile"),
    "admin": (".", "frontend/admin/Dockerfile"),
    "avatar": (".", "frontend/app/Dockerfile"),
    "api": ("brain/api", "brain/api/Dockerfile"),
    "embedding": ("brain/embedding", "brain/embedding/Dockerfile"),
}


class ImageFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Image tests")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("config", "commit.gpgsign", "false")
        for path in (WORKFLOW, "scripts/image_fingerprint.py"):
            self.write(path, (ROOT / path).read_text())
        for _, dockerfile in IMAGES.values():
            self.write(dockerfile, (ROOT / dockerfile).read_text())
        for path in (
            "backend/app/main.py", "backend/requirements.txt",
            "frontend/admin/src/main.ts", "frontend/app/src/main.ts",
            "frontend/avatar-sdk/src/index.ts", "contracts/schema.json",
            "brain/api/main.py", "brain/embedding/app.py",
            ".dockerignore", "backend/.dockerignore", "README.md",
        ):
            self.write(path, "initial\n")
        for context, dockerfile in IMAGES.values():
            for source in copy_sources((self.repo / dockerfile).read_text()):
                target = self.repo / context / source
                if (ROOT / context / source).is_dir():
                    target /= ".fixture"
                if target.exists():
                    continue
                self.write(str(target.relative_to(self.repo)), "fixture\n")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True
        ).strip()

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def key(self, image="backend", **kwargs):
        return fingerprint(self.repo, *IMAGES[image], **kwargs)[0]

    def keys(self):
        return {image: self.key(image) for image in IMAGES}

    def changed(self, before):
        return {image for image in IMAGES if self.key(image) != before[image]}

    def decide(
        self, image, published=(), *, digest="sha256:base", event="push",
        base_only=False, force=False,
    ):
        workflow = (ROOT / WORKFLOW).read_text()
        name = (
            "Decide whether the base image needs rebuilding"
            if base_only else "Decide whether this image needs rebuilding"
        )
        step = workflow.split(
            "      - name: " + name + "\n", 1
        )[1].split("      - name:", 1)[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        mockbin = Path(self.temp.name) / "bin"
        mockbin.mkdir(exist_ok=True)
        docker = mockbin / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "assert sys.argv[1:3] == ['manifest', 'inspect']\n"
            "sys.exit(0 if sys.argv[3] in json.loads(os.environ['PUBLISHED']) else 1)\n"
        )
        docker.chmod(0o755)
        output = Path(self.temp.name) / "outputs"
        output.write_text("")
        context, dockerfile = IMAGES[image]
        env = {
            **os.environ,
            "PATH": str(mockbin) + os.pathsep + os.environ["PATH"],
            "IMAGE": "test/" + image,
            "CONTEXT": context,
            "DOCKERFILE": dockerfile,
            "IMAGE_NAME": image,
            "BASE_DIGEST": digest,
            "FORCE": "true" if force else "false",
            "BEFORE": self.git("rev-parse", "HEAD"),
            "GITHUB_SHA": self.git("rev-parse", "HEAD"),
            "GITHUB_EVENT_NAME": event,
            "GITHUB_OUTPUT": str(output),
            "PUBLISHED": json.dumps(list(published)),
        }
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.repo, env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_single_commit_only_rebuilds_affected_image(self):
        for image, path in (
            ("backend", "backend/app/main.py"),
            ("admin", "frontend/admin/src/main.ts"),
            ("avatar", "frontend/app/src/main.ts"),
            ("api", "brain/api/main.py"),
            ("embedding", "brain/embedding/app.py"),
        ):
            with self.subTest(image=image):
                before = self.keys()
                self.write(path, "changed\n")
                self.commit()
                self.assertEqual(self.changed(before), {image})

    def test_multiple_commit_push_keeps_earlier_changes(self):
        before = self.key()
        self.write("backend/app/main.py", "changed\n")
        self.commit()
        self.write("README.md", "unrelated final commit\n")
        self.commit()
        self.assertEqual(self.git("diff", "--name-only", "HEAD~1", "HEAD"), "README.md")
        self.assertNotEqual(self.key(), before)

    def test_shared_inputs_select_their_consumers(self):
        for path, expected in (
            ("contracts/schema.json", {"admin", "avatar"}),
            ("frontend/avatar-sdk/src/index.ts", {"admin"}),
            (".dockerignore", {"admin", "avatar"}),
            ("backend/.dockerignore", {"backend"}),
        ):
            with self.subTest(path=path):
                before = self.keys()
                self.write(path, "changed\n")
                self.commit()
                self.assertEqual(self.changed(before), expected)

    def test_workflow_change_invalidates_every_image(self):
        before = self.keys()
        with (self.repo / WORKFLOW).open("a") as stream:
            stream.write("\n# workflow changed\n")
        self.commit()
        self.assertEqual(self.changed(before), set(IMAGES))

    def test_new_and_moved_copy_sources_are_discovered(self):
        dockerfile = "frontend/admin/Dockerfile"
        original = (self.repo / dockerfile).read_text()
        self.write(dockerfile, original + "\nCOPY shared-ui /shared-ui\n")
        self.write("shared-ui/theme.css", "first\n")
        self.commit()
        before = self.keys()
        self.write("shared-ui/theme.css", "second\n")
        self.commit()
        self.assertEqual(self.changed(before), {"admin"})
        self.write(dockerfile, original + "\nCOPY moved-ui /shared-ui\n")
        self.write("moved-ui/theme.css", "moved\n")
        self.commit()
        before = self.keys()
        self.write("moved-ui/theme.css", "changed after move\n")
        self.commit()
        self.assertEqual(self.changed(before), {"admin"})

    def test_deleted_or_executable_input_invalidates_image(self):
        before = self.key()
        (self.repo / "backend/app/main.py").chmod(0o755)
        self.commit()
        self.assertNotEqual(self.key(), before)
        before = self.key()
        (self.repo / "backend/app/main.py").unlink()
        self.commit()
        self.assertNotEqual(self.key(), before)

    def test_runner_changes_do_not_rebuild_base(self):
        before = self.key(base_only=True)
        path = "backend/Dockerfile"
        self.write(path, (self.repo / path).read_text() + "\nENV EXAMPLE=1\n")
        self.commit()
        self.assertEqual(self.key(base_only=True), before)

    def test_base_stage_changes_and_inputs_invalidate_base(self):
        before = self.key(base_only=True)
        path = "backend/Dockerfile"
        content = (self.repo / path).read_text().replace(
            "\nFROM ${BASE_IMAGE}", "\nCOPY base-input.txt /base-input.txt\nFROM ${BASE_IMAGE}"
        )
        self.write(path, content)
        self.write("backend/base-input.txt", "first\n")
        self.commit()
        self.assertNotEqual(self.key(base_only=True), before)
        before = self.key(base_only=True)
        self.write("backend/base-input.txt", "second\n")
        self.commit()
        self.assertNotEqual(self.key(base_only=True), before)

    def test_forced_base_rebuild_digest_invalidates_backend(self):
        old = self.key(base_digest="sha256:old")
        published = {"test/backend:source-" + old}
        result = self.decide("backend", published, digest="sha256:new")
        self.assertEqual(result["rebuild"], "true")

    def test_cancelled_or_failed_build_cannot_reuse_stale_latest(self):
        for image in IMAGES:
            with self.subTest(image=image):
                old = self.decide(image)
                path = {
                    "backend": "backend/app/main.py",
                    "admin": "frontend/admin/src/main.ts",
                    "avatar": "frontend/app/src/main.ts",
                    "api": "brain/api/main.py",
                    "embedding": "brain/embedding/app.py",
                }[image]
                self.write(path, "unpublished build\n")
                self.commit()
                self.write("README.md", "next commit after cancellation: " + image)
                self.commit()
                published = {old["source_ref"], "test/" + image + ":latest"}
                result = self.decide(image, published)
                self.assertEqual(result["rebuild"], "true")
                self.assertNotEqual(result["source_ref"], old["source_ref"])

    def test_only_matching_published_inputs_allow_reuse(self):
        for image in IMAGES:
            with self.subTest(image=image):
                initial = self.decide(image)
                self.assertEqual(initial["rebuild"], "true")
                result = self.decide(image, {initial["source_ref"]})
                self.assertEqual(result["rebuild"], "false")
                forced = self.decide(
                    image, {initial["source_ref"]}, event="workflow_dispatch"
                )
                self.assertEqual(forced["rebuild"], "true")

    def test_base_decision_reuses_only_matching_published_inputs(self):
        initial = self.decide("backend", base_only=True)
        self.assertEqual(initial["rebuild"], "true")
        published = {initial["source_ref"]}
        reused = self.decide("backend", published, base_only=True)
        self.assertEqual(reused["rebuild"], "false")
        forced = self.decide(
            "backend", published, base_only=True,
            event="workflow_dispatch", force=True,
        )
        self.assertEqual(forced["rebuild"], "true")
        manual = self.decide(
            "backend", published, base_only=True, event="workflow_dispatch"
        )
        self.assertEqual(manual["rebuild"], "false")

        self.write("backend/app/main.py", "runner-only change\n")
        self.commit()
        unchanged = self.decide("backend", published, base_only=True)
        self.assertEqual(unchanged["rebuild"], "false")

        path = "backend/Dockerfile"
        self.write(path, (self.repo / path).read_text().replace(
            "AS builder", "AS builder\nENV BASE_REVISION=2", 1
        ))
        self.commit()
        self.write("README.md", "commit after cancelled base build\n")
        self.commit()
        stale = self.decide(
            "backend", published | {"test/backend:latest"}, base_only=True
        )
        self.assertEqual(stale["rebuild"], "true")
        self.assertNotEqual(stale["source_ref"], initial["source_ref"])

    def test_base_job_exports_only_digest_and_backend_pins_it(self):
        workflow = (ROOT / WORKFLOW).read_text()
        base_job = workflow.split("  backend-base:\n", 1)[1].split(
            "  build-and-push:\n", 1
        )[0]
        outputs = base_job.split("    outputs:\n", 1)[1].split(
            "    steps:\n", 1
        )[0]
        # A registry name includes DOCKERHUB_USERNAME, which is a secret;
        # GitHub suppresses secret-containing outputs between jobs.
        self.assertEqual(
            outputs.strip(),
            "digest: ${{ steps.resolve.outputs.digest }}",
        )
        self.assertIn(
            "BASE_IMAGE=${{ secrets.DOCKERHUB_USERNAME }}"
            "/openvman-backend-base@${{ needs.backend-base.outputs.digest }}",
            workflow,
        )
        self.assertNotIn("needs.backend-base.outputs.image_ref", workflow)

    def test_supported_and_unsupported_copy_syntax(self):
        self.assertEqual(
            copy_sources('COPY ["dir with spaces", "/app"]\nCOPY --from=builder /x /x'),
            ["dir with spaces"],
        )
        for line in (
            "COPY $SOURCE /app", "ADD https://example.invalid/file /app",
            "COPY <<EOF /app", "COPY --unknown=1 src /app",
            "RUN --mount=type=bind,source=src,target=/src make",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                copy_sources(line)

    def test_missing_copy_source_fails_before_reusing_an_image(self):
        path = "frontend/admin/Dockerfile"
        self.write(path, (self.repo / path).read_text() + "\nCOPY missing /missing\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "no committed files: missing"):
            self.key("admin")


if __name__ == "__main__":
    unittest.main()
