from __future__ import annotations

import pytest

from safe_repl import process_control


class _FakeProcess:
    def __init__(self, *, alive_after_join: bool = False) -> None:
        self.alive_after_join = alive_after_join
        self.join_calls: list[float] = []
        self.kill_calls = 0
        self.terminate_calls = 0

    def join(self, *, timeout: float) -> None:
        self.join_calls.append(timeout)

    def is_alive(self) -> bool:
        return self.alive_after_join

    def kill(self) -> None:
        self.kill_calls += 1

    def terminate(self) -> None:
        self.terminate_calls += 1


class _FakeConnection:
    def __init__(self, *, poll_result: bool, recv_value: object = "ok") -> None:
        self.poll_result = poll_result
        self.recv_value = recv_value

    def poll(self, _timeout: float | None) -> bool:
        return self.poll_result

    def recv(self) -> object:
        return self.recv_value


def test_validate_process_isolation_support_rejects_non_default_start_method() -> None:
    with pytest.raises(RuntimeError, match="Unsupported process start method"):
        process_control.validate_process_isolation_support("spawn")


def test_validate_process_isolation_support_rejects_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_control.multiprocessing, "get_all_start_methods", lambda: ["spawn"])

    with pytest.raises(RuntimeError, match="not supported"):
        process_control.validate_process_isolation_support(process_control.DEFAULT_START_METHOD)


def test_finalize_process_terminates_when_requested() -> None:
    process = _FakeProcess(alive_after_join=False)

    process_control.finalize_process(process, terminate=True)

    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert len(process.join_calls) == 1


def test_finalize_process_kills_stuck_process() -> None:
    process = _FakeProcess(alive_after_join=True)

    process_control.finalize_process(process)

    assert process.terminate_calls == 0
    assert process.kill_calls == 1
    assert len(process.join_calls) == 2


def test_await_worker_response_returns_payload_on_time() -> None:
    response = process_control.await_worker_response(
        _FakeConnection(poll_result=True, recv_value={"ok": True}),
        _FakeProcess(),
        timeout=0.1,
    )

    assert response == {"ok": True}


def test_await_worker_response_terminates_and_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"terminate": False}

    def _fake_finalize(_process: object, *, terminate: bool = False) -> None:
        called["terminate"] = terminate

    monkeypatch.setattr(process_control, "finalize_process", _fake_finalize)

    with pytest.raises(TimeoutError, match="Execution timed out"):
        process_control.await_worker_response(
            _FakeConnection(poll_result=False),
            _FakeProcess(),
            timeout=0.01,
        )

    assert called["terminate"] is True
