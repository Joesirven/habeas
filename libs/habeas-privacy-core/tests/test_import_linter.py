import shutil
import subprocess

from habeas_privacy_core.db.migrations import repo_root


def test_import_linter_passes():
    lint_imports = shutil.which("lint-imports")
    assert lint_imports is not None, "lint-imports CLI not installed"
    result = subprocess.run(
        [lint_imports],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
