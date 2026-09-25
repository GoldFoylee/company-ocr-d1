"""The local Git hook must reject a tracked raw fixture before commit."""

import shutil
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def test_installed_pre_commit_hook_rejects_staged_raw_fixture(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in (
        "check_no_raw_fixtures.sh",
        "pre_commit_guard.sh",
        "install_dev_hooks.sh",
    ):
        target = scripts / name
        shutil.copy2(SCRIPTS / name, target)
        target.chmod(0o755)

    assert _git(tmp_path, "init", "-q").returncode == 0
    assert _git(tmp_path, "config", "user.name", "Guard Test").returncode == 0
    assert _git(tmp_path, "config", "user.email", "guard-test@example.invalid").returncode == 0
    install = subprocess.run(
        [str(scripts / "install_dev_hooks.sh")], cwd=tmp_path, capture_output=True, text=True
    )
    assert install.returncode == 0, install.stderr
    assert (tmp_path / ".git" / "hooks" / "pre-commit").is_file()

    raw = tmp_path / "tests" / "fixtures" / "raw" / "dummy.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("synthetic test marker\n")
    assert _git(tmp_path, "add", "tests/fixtures/raw/dummy.txt").returncode == 0

    commit = _git(tmp_path, "commit", "-m", "dummy")

    assert commit.returncode != 0
    assert "raw fixtures must never be committed" in commit.stderr
    assert _git(tmp_path, "rev-list", "--count", "HEAD").returncode != 0
