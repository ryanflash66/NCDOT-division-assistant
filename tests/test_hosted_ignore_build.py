"""hosted/scripts/ignore_build.sh, Vercel's Ignored Build Step: exit 0 skips the build, 1 builds."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "hosted/scripts/ignore_build.sh"
BASH = shutil.which("bash")
if BASH and "system32" in BASH.lower():
    BASH = None  # WSL's bash.exe launcher: it doesn't pass the Windows environment or arguments through reliably

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash (Linux, macOS or Git Bash)")


def _exit_code(vercel_env, message):
    command = 'export VERCEL_ENV="$1" VERCEL_GIT_COMMIT_MESSAGE="$2"; exec bash "$3"'
    run = subprocess.run([BASH, "-c", command, "_", vercel_env, message, SCRIPT], cwd=ROOT, capture_output=True)
    return run.returncode


def test_production_builds():
    assert _exit_code("production", "Merge pull request #44") == 1


def test_a_preview_is_skipped():
    assert _exit_code("preview", "Fix the citation check") == 0


def test_a_preview_builds_when_the_commit_asks_for_one():
    assert _exit_code("preview", "Try the new reranker [preview]") == 1


def test_the_tag_counts_only_in_the_first_line():
    # A body that describes the tag (as the commit adding this script did) is not a request for a preview.
    assert _exit_code("preview", "Build previews on request\n\nBuilds only when the message contains [preview].") == 0
