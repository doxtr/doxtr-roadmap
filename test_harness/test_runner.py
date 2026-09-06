"""Test harness runner for doxtr_roadmap.

Runs ``sphinx-build -b html`` in the test_harness directory and verifies:
- Exit code 0
- No ERROR lines in stdout/stderr
- Output HTML files exist for each test case
"""

import os
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
BUILD_DIR = HARNESS_DIR / "_build" / "html"
TEST_CASES_DIR = HARNESS_DIR / "source" / "_test_cases"


def run_sphinx_build(fail_on_pending: bool = False):
    """Run sphinx-build and return (returncode, stdout+stderr combined)."""
    cmd = [
        sys.executable, "-m", "sphinx",
        "-b", "html",
        "-E",           # fresh env
        "-W",           # warnings as errors only when fail_on_pending
        str(HARNESS_DIR),
        str(BUILD_DIR),
    ]
    if not fail_on_pending:
        # Remove -W for lenient mode
        cmd = [c for c in cmd if c != "-W"]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(HARNESS_DIR),
    )
    combined = result.stdout + result.stderr
    return result.returncode, combined


def check_output(output: str, fail_on_errors: bool = True):
    """Scan output for ERROR lines."""
    errors = [line for line in output.splitlines() if "ERROR" in line.upper()]
    if errors and fail_on_errors:
        print("BUILD ERRORS FOUND:")
        for e in errors:
            print(f"  {e}")
        return False
    return True


def check_html_files():
    """Verify expected HTML output files exist and contain a rendered plantuml image."""
    # Test case RST files live under source/_test_cases/; Sphinx mirrors
    # that hierarchy, so the HTML lands at _build/html/source/_test_cases/.
    expected = [
        "roadmap_inline.html",
        "roadmap_file.html",
        "roadmap_filtered.html",
        "roadmap_link_appendix.html",
    ]
    test_cases_html_dir = BUILD_DIR / "source" / "_test_cases"
    missing = []
    no_image = []
    no_link = []
    for fname in expected:
        html_path = test_cases_html_dir / fname
        if not html_path.exists():
            missing.append(str(html_path))
            continue
        # T-13: assert plantuml actually rendered — look for <img or <object tag
        content = html_path.read_text(encoding="utf-8", errors="replace")
        if "<img" not in content and "<object" not in content:
            no_image.append(str(html_path))
        # For the link appendix test case, verify a real <a href appears
        if fname == "roadmap_link_appendix.html":
            if '<a ' not in content or 'href' not in content:
                no_link.append(str(html_path))
    return missing, no_image, no_link


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Run doxtr-roadmap test harness")
    parser.add_argument(
        "--fail-on-pending",
        action="store_true",
        help="Treat sphinx warnings as errors (strict mode).",
    )
    args = parser.parse_args(argv)

    print(f"Running sphinx-build in {HARNESS_DIR} ...")
    rc, output = run_sphinx_build(fail_on_pending=args.fail_on_pending)
    print(output)

    passed = True

    if rc != 0:
        print(f"FAIL: sphinx-build exited with code {rc}")
        passed = False
    else:
        print("OK: sphinx-build exit code 0")

    if not check_output(output, fail_on_errors=True):
        passed = False

    missing, no_image, no_link = check_html_files()
    if missing:
        print("FAIL: Missing expected HTML output files:")
        for m in missing:
            print(f"  {m}")
        passed = False
    elif no_image:
        print("FAIL: HTML files present but contain no <img>/<object> (plantuml did not render):")
        for f in no_image:
            print(f"  {f}")
        passed = False
    elif no_link:
        print("FAIL: Link appendix HTML present but contains no <a href> (appendix not rendered):")
        for f in no_link:
            print(f"  {f}")
        passed = False
    else:
        print("OK: All expected HTML files generated with rendered images and link appendix")

    if passed:
        print("\nTest harness PASSED.")
        return 0
    else:
        print("\nTest harness FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
