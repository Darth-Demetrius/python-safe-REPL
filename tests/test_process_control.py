from __future__ import annotations

import pytest

from safe_repl import PermissionLevel, Permissions
from safe_repl.worker_session import WorkerSession


class _FakeProcess:
    def __init__(self, *, alive: bool = True, alive_after_join: bool = False) -> None:
        self.alive = alive
        self.alive_after_join = alive_after_join
        self._joined = False
        self.join_calls: list[float] = []
        self.kill_calls = 0
        self.terminate_calls = 0

    def join(self, *, timeout: float) -> None:
        self.join_calls.append(timeout)
        self._joined = True

    def is_alive(self) -> bool:
        if self._joined:
            return self.alive_after_join
        return self.alive

    def kill(self) -> None:
        self.kill_calls += 1

    def terminate(self) -> None:
        self.terminate_calls += 1


class _FakeConnection:
    def __init__(self, *, poll_result: bool, recv_value: object = "ok") -> None:
        self.poll_result = poll_result
        self.recv_value = recv_value
        self.sent: list[dict[str, object]] = []

    def poll(self, _timeout: float | None) -> bool:
        return self.poll_result

    def recv(self) -> object:
        return self.recv_value

    def send(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


def _build_session() -> WorkerSession:
    return WorkerSession(
        perms=Permissions(base_perms=PermissionLevel.LIMITED),
        user_vars={},
    )


def test_finalize_terminates_when_requested() -> None:
    session = _build_session()
    process = _FakeProcess(alive_after_join=False)
    session._process = process

    session.finalize(terminate=True)

    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert len(process.join_calls) == 1


def test_finalize_kills_stuck_process() -> None:
    session = _build_session()
    process = _FakeProcess(alive_after_join=True)
    session._process = process

    session.finalize()

    assert process.terminate_calls == 0
    assert process.kill_calls == 1
    assert len(process.join_calls) == 2


def test_request_returns_payload_on_time() -> None:
    session = _build_session()
    session._process = _FakeProcess()
    session._parent_conn = _FakeConnection(
        poll_result=True,
        recv_value={
            "ok": True,
            "result": 7,
            "user_vars": {"x": 1},
            "output": None,
            "exception_type": None,
            "message": None,
        },
    )

    response = session._request({"op": "exec", "code": "x = 1"})

    assert response["ok"] is True
    assert response["result"] == 7


def test_request_terminates_and_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _build_session()
    session._process = _FakeProcess()
    session._parent_conn = _FakeConnection(poll_result=False)

    called = {"terminate": False}

    def _fake_finalize(*, terminate: bool = False) -> None:
        called["terminate"] = terminate

    monkeypatch.setattr(session, "finalize", _fake_finalize)

    with pytest.raises(TimeoutError, match="Execution timed out"):
        session._request({"op": "exec", "code": "x = 1"})

    assert called["terminate"] is True


def test_exec_updates_session_user_vars() -> None:
    session = _build_session()
    session._process = _FakeProcess()
    session._parent_conn = _FakeConnection(
        poll_result=True,
        recv_value={
            "ok": True,
            "result": None,
            "user_vars": {"x": 5},
            "output": None,
            "exception_type": None,
            "message": None,
        },
    )

    response = session.exec("x = 5")

    assert response["ok"] is True
    assert session._user_vars == {"x": 5}
