"""Try IPv4 addresses before IPv6 ones.

Some Wi-Fi (the Cal Hacks venue, 2026-10-25) hands out IPv6 that goes nowhere. curl falls back to
IPv4 by itself, but Cartesia's websocket tried the IPv6 address, hung for its whole 10 s handshake
timeout and never tried IPv4: "ALTA's voice service isn't responding". IPv4 first fixes it, and costs
nothing where IPv6 works.
"""

import socket


def prefer_ipv4() -> None:
    """Make socket.getaddrinfo list IPv4 results first. Safe to call more than once."""
    current = socket.getaddrinfo
    if getattr(current, "_ipv4_first", False):
        return

    def getaddrinfo(*args, **kwargs):
        return sorted(current(*args, **kwargs), key=lambda r: r[0] != socket.AF_INET)  # stable: keeps order within a family

    getaddrinfo._ipv4_first = True
    socket.getaddrinfo = getaddrinfo
