import socket

from bench import net

V6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2600::1", 443, 0, 0))
V4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", 443))


def test_ipv4_addresses_come_first_so_a_dead_ipv6_route_cant_stall_a_connect(monkeypatch):
    """Venue Wi-Fi with broken IPv6: Cartesia's websocket hung 10 s on its IPv6 address and never tried IPv4."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [V6, V4])
    net.prefer_ipv4()
    assert socket.getaddrinfo("api.cartesia.ai", 443) == [V4, V6]


def test_installing_twice_wraps_once(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append(1) or [V6, V4])
    net.prefer_ipv4()
    net.prefer_ipv4()
    socket.getaddrinfo("x", 1)
    assert calls == [1]


def test_ipv6_only_hosts_still_resolve(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [V6])
    net.prefer_ipv4()
    assert socket.getaddrinfo("v6only", 443) == [V6]
