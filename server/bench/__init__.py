"""ALTA server package. Layout and contracts: docs/CONTRACTS.md."""

from .net import prefer_ipv4

prefer_ipv4()  # before anything opens a connection (server, preflight, talk, scenarios)
