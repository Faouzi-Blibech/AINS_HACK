"""Minimal example agent for Cassette Import.

Makes one HTTPS request with httpx so Cassette has something to record. No API
key and no external setup are needed. It exists so a tester can import an agent
immediately and see a real HTTP step captured.

Import it from the UI (Connect agent -> Import):
  source  = examples/http_agent      (or /app/examples/http_agent under Docker)
  command = python main.py

The single httpx call is routed through the recording proxy; because the run
is HTTPS, it also exercises the proxy CA trust wired in by the import driver.
"""
from __future__ import annotations

import httpx

# A small, stable public endpoint. The point is to make a real HTTPS call that
# Cassette captures, not the content of the response.
ENDPOINT = "https://jsonplaceholder.typicode.com/todos/1"


def fetch_todo() -> dict:
    resp = httpx.get(ENDPOINT, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    todo = fetch_todo()
    print("example agent fetched:", todo)


if __name__ == "__main__":
    main()
