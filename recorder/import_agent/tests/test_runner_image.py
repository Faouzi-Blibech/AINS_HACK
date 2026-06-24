import subprocess
from recorder.import_agent import image as R


def test_image_exists_true_when_inspect_succeeds():
    def fake(cmd, **kw):
        assert cmd[:3] == ["docker", "image", "inspect"]
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
    assert R.image_exists(runner=fake) is True


def test_image_exists_false_when_inspect_fails():
    def fake(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No such image")
    assert R.image_exists(runner=fake) is False


def test_ensure_image_builds_when_missing():
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    tag = R.ensure_image(runner=fake)
    assert tag == R.IMAGE_TAG
    build = next(c for c in calls if c[:2] == ["docker", "build"])
    assert "-t" in build and R.IMAGE_TAG in build
    assert "-f" in build  # references the Dockerfile
