"""hosted/scripts/build.sh and vercel.json: the page images are a build switch and stay out of the function (DAR-665).

The build's tools are stubbed (npm, python3, uv log their arguments), so nothing is downloaded or rendered.
"""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "hosted" / "scripts" / "build.sh"
BASH = shutil.which("bash")
if BASH and "system32" in BASH.lower():
    BASH = None  # WSL's launcher doesn't pass the Windows environment through reliably

needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash (Linux, macOS or Git Bash)")


def _run_build(tmp_path, render_pages=None, pip_works=True):
    """Run build.sh with stub tools; the lines the tools were called with, the exit code and the output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    fail_pip = "" if pip_works else 'case "$*" in *"-m pip"*) exit 1;; esac\n'
    stubs = {
        "npm": 'echo "npm $*" >> "$CALLS"\n',
        "python3": f'echo "python3 PYTHONPATH=${{PYTHONPATH:-}} $*" >> "$CALLS"\n{fail_pip}',
        "uv": 'echo "uv $*" >> "$CALLS"\n' + ("" if pip_works else "exit 1\n"),
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\n" + body, newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "hosted"
    (work / "web").mkdir(parents=True)
    env = dict(os.environ, CALLS=str(log), PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    env.pop("RENDER_PAGES", None)
    if render_pages is not None:
        env["RENDER_PAGES"] = render_pages
    run = subprocess.run([BASH, str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return calls, run.returncode, run.stdout


@needs_bash
@pytest.mark.parametrize("value", [None, "", "0"])
def test_without_the_switch_nothing_is_downloaded_or_rendered(tmp_path, value):
    calls, code, _ = _run_build(tmp_path, value)
    assert code == 0
    assert any("fetch_models.py" in c for c in calls)
    assert not any("fetch_documents" in c or "render_pages" in c or "pip" in c for c in calls)


@needs_bash
def test_the_switch_downloads_the_documents_and_renders_the_indexed_pages_into_public_pages(tmp_path):
    calls, code, _ = _run_build(tmp_path, "1")
    assert code == 0
    assert any("fetch_documents.py" in c for c in calls)
    render = next(c for c in calls if "render_pages.py" in c)
    assert "--only-indexed index/chunks.json" in render and "--out public/pages" in render
    # pymupdf is installed into its own folder and only the render sees it: the function bundle is
    # built from the build's Python environment and must not gain a render-only package.
    install = next(c for c in calls if "-m pip install" in c)
    target = install.split("--target ")[1].split()[0]
    assert "PYTHONPATH=" + target in render  # appended to, not replacing, any PYTHONPATH already set


@needs_bash
def test_a_failed_install_cannot_fail_the_deploy(tmp_path):
    calls, code, out = _run_build(tmp_path, "1", pip_works=False)
    assert code == 0
    assert any(c.startswith("uv pip install") and "--target" in c for c in calls)  # the fallback was tried
    assert "page images incomplete" in out
    assert not any("render_pages" in c for c in calls)


def test_the_page_images_stay_out_of_the_function_bundle():
    config = json.loads((ROOT / "hosted" / "vercel.json").read_text(encoding="utf-8"))
    function = config["functions"]["index.py"]
    # public/ is bundled (the page and the manifest), the images and the downloaded PDFs are not.
    assert function["includeFiles"] == "public/**"
    excluded = function["excludeFiles"].strip("{}").split(",")
    assert "public/pages/**" in excluded and "documents/**" in excluded
    assert config["buildCommand"] == "bash scripts/build.sh"
    assert len(config["buildCommand"]) <= 256
