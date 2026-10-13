import socket

import pytest


@pytest.fixture(autouse=True)
def network_off(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Network is disabled in offline tests")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
