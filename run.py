"""Launch the Jira Manager web app with automatic port selection.

    python run.py            # auto-detects a working port (prefers 8123)
    python run.py 9000       # try 9000 first, then auto-detect

If the preferred port is blocked (some corporate machines forbid certain ports)
or already in use, the launcher searches a list of candidate ports and starts on
the first that works, then opens your browser there. The web UI knows the same
candidate list, so if the server ever moves the page can point you to the new
address.
"""
import socket
import sys
import webbrowser

import uvicorn

# Keep this list in sync with PORT_CANDIDATES in frontend/app.js
PORT_CANDIDATES = [8123, 8200, 8456, 8765, 9000, 9123, 9456, 7123, 7777, 10123]


def can_bind(port: int) -> bool:
    """True if we can bind 127.0.0.1:<port> right now (free and allowed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(preferred: int | None = None) -> int:
    order: list[int] = []
    if preferred:
        order.append(preferred)
    order += [p for p in PORT_CANDIDATES if p != preferred]
    for p in order:
        if can_bind(p):
            return p
    # Last resort: let the OS hand us any free port.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


if __name__ == "__main__":
    preferred = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    port = pick_port(preferred)
    url = f"http://127.0.0.1:{port}"

    if port != preferred:
        print(f"Preferred port {preferred} was unavailable — "
              f"searched and found a working port.")
    print("=" * 60)
    print(f"  Jira Manager is running at:  {url}")
    print("  Open that address in your browser (Ctrl+C to stop).")
    print("=" * 60)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False)
