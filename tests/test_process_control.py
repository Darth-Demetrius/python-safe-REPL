from __future__ import annotations

import multiprocessing

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


def _noop_worker() -> None:
    return None


def test_spawn_context_process_returns_process_instance() -> None:
    ctx = multiprocessing.get_context("spawn")

    process = process_control.spawn_context_process(
        context=ctx,
        target=_noop_worker,
        kwargs={},
        daemon=True,
    )

    assert process.daemon is True


def test_spawn_context_process_rejects_missing_process_factory() -> None:
    context = object()

    with pytest.raises(RuntimeError, match="does not provide a Process factory"):
        process_control.spawn_context_process(
            context=context,
            target=_noop_worker,
            kwargs={},
            daemon=False,
        )


def test_spawn_context_process_rejects_unsupported_process_type() -> None:
    class _InvalidContext:
        def Process(self, **_kwargs: object) -> object:  # noqa: N802
            return object()

    with pytest.raises(RuntimeError, match="unsupported process type"):
        process_control.spawn_context_process(
            context=_InvalidContext(),
            target=_noop_worker,
            kwargs={},
            daemon=False,
        )


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
