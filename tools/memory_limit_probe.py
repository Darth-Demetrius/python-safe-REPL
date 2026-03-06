"""Memory limit probe for experimenting with RLIMIT and tracemalloc.

Run: ./.venv/bin/python tools/memory_limit_probe.py
"""

from __future__ import annotations

import argparse
import tracemalloc
from typing import Callable

try:
    import resource
except ImportError:  # pragma: no cover - not available on some platforms
    resource = None


def _apply_limits(limit_bytes: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    if resource is None:
        print("resource module not available; skipping RLIMIT.")
        return None, None

    previous_as = resource.getrlimit(resource.RLIMIT_AS)
    print(f"RLIMIT_AS before: soft={previous_as[0]} hard={previous_as[1]}")
    previous_data = None

    soft, hard = previous_as
    new_hard = min(limit_bytes, hard)
    new_soft = min(limit_bytes, new_hard)
    resource.setrlimit(resource.RLIMIT_AS, (new_soft, new_hard))
    print(f"RLIMIT_AS after: soft={new_soft} hard={new_hard}")

    if hasattr(resource, "RLIMIT_DATA"):
        previous_data = resource.getrlimit(resource.RLIMIT_DATA)
        print(f"RLIMIT_DATA before: soft={previous_data[0]} hard={previous_data[1]}")
        data_soft, data_hard = previous_data
        new_data_hard = min(limit_bytes, data_hard)
        new_data_soft = min(limit_bytes, new_data_hard)
        resource.setrlimit(resource.RLIMIT_DATA, (new_data_soft, new_data_hard))
        print(f"RLIMIT_DATA after: soft={new_data_soft} hard={new_data_hard}")

    return previous_as, previous_data


def _restore_limits(previous_as, previous_data) -> None:
    if resource is None:
        return
    if previous_as is not None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, previous_as)
        except (OSError, ValueError):
            pass
    if previous_data is not None and hasattr(resource, "RLIMIT_DATA"):
        try:
            resource.setrlimit(resource.RLIMIT_DATA, previous_data)
        except (OSError, ValueError):
            pass


def _report_peak(label: str, limit_bytes: int) -> None:
    current, peak = tracemalloc.get_traced_memory()
    over = "YES" if peak > limit_bytes else "NO"
    print(
        f"{label}: current={current / 1024:.1f}KB "
        f"peak={peak / 1024:.1f}KB over_limit={over}"
    )


def _run_probe(title: str, metric_label: str, allocator: Callable[[], object], limit_bytes: int) -> None:
    print(title)
    try:
        data = allocator()
        _report_peak(metric_label, limit_bytes)
        del data
    except MemoryError as exc:
        print(f"MemoryError: {exc}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe memory behavior under RLIMIT + tracemalloc.")
    parser.add_argument(
        "--limit-bytes",
        type=int,
        default=1024,
        help="Soft memory limit in bytes to apply before probes (default: 1024).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    limit_bytes = args.limit_bytes
    print(f"Setting memory limit to {limit_bytes} bytes")

    previous_as, previous_data = _apply_limits(limit_bytes)
    tracemalloc.start()
    tracemalloc.reset_peak()

    try:
        _run_probe(
            "Allocating list of 10 million ints...",
            "list(range)",
            lambda: list(range(10_000_000)),
            limit_bytes,
        )
        _run_probe(
            "Allocating list of 100k strings (1KB each)...",
            "list(strings)",
            lambda: [str(i).zfill(1024) for i in range(100_000)],
            limit_bytes,
        )
        _run_probe(
            "Allocating 128MB bytearray...",
            "bytearray",
            lambda: bytearray(128 * 1024 * 1024),
            limit_bytes,
        )

    finally:
        tracemalloc.stop()
        _restore_limits(previous_as, previous_data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
