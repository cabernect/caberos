import os
import socket
import sys
import time

import pytest

from agentos.gateway_entry import _claim_port_or_die


@pytest.mark.skipif(os.name != "posix" or sys.platform == "cygwin", reason="POSIX socket reuse")
def test_port_preflight_allows_restart_after_server_closes_connection():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _ = listener.accept()
            with connection:
                # Server closes first, leaving TIME_WAIT after both sockets close.
                connection.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b""

    _claim_port_or_die("127.0.0.1", port)


def test_port_preflight_still_rejects_live_listener(monkeypatch, capsys):
    monkeypatch.setattr("agentos.gateway_entry._port_holder", lambda port: "test listener")
    with socket.socket() as listener:
        if os.name == "posix":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with monkeypatch.context() as clock:
            ticks = iter((0.0, 9.0))
            clock.setattr(time, "monotonic", lambda: next(ticks, 9.0))
            with pytest.raises(SystemExit) as error:
                _claim_port_or_die("127.0.0.1", port)
        assert error.value.code == 3
        assert "test listener" in capsys.readouterr().err
        assert listener.getsockname()[1] == port
