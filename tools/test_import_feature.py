#!/usr/bin/env python3
"""Manual probe script for the --import feature of safe_repl.

Run: ./.venv/bin/python tools/test_import_feature.py
"""

import subprocess
import sys

def run_case(import_spec: str, test_code: str, expected_output: str | None = None) -> bool:
    """Run one import probe case and return whether it succeeded."""
    print(f"\n{'='*60}")
    print(f"Testing: --import '{import_spec}'")
    print(f"Code: {test_code}")
    print(f"{'='*60}")

    cmd = [
        sys.executable,
        "-m",
        "safe_repl",
        "--import", import_spec
    ]

    try:
        result = subprocess.run(
            cmd,
            input=f"{test_code}\nquit\n",
            capture_output=True,
            text=True,
            timeout=5
        )

        print("STDERR:", result.stderr.strip() if result.stderr.strip() else "(none)")
        print("STDOUT:", result.stdout)

        if expected_output and expected_output in result.stdout:
            print("✓ PASS")
        elif expected_output:
            print(f"✗ FAIL: Expected '{expected_output}' in output")
            return False

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("✗ TIMEOUT")
        return False
    except Exception as exc:
        print(f"✗ ERROR: {exc}")
        return False


def main() -> int:
    cases = [
        ("json", "json.dumps({'a': 1})", None),
        ("json as j", "j.dumps({'b': 2})", None),
        ("json:dumps", "dumps({'c': 3})", None),
        ("json:dumps as d", "d({'d': 4})", None),
        ("json:dumps, loads", "loads(dumps({'e': 5}))", None),
    ]

    print("Testing --import feature")
    passed = sum(run_case(import_spec, test_code, expected) for import_spec, test_code, expected in cases)
    total = len(cases)

    print("\n" + "=" * 60)
    print(f"Completed {total} cases: {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
