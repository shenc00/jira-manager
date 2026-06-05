"""Launch the Jira Manager web app with automatic port selection.

    python run.py            # auto-detects a working port (prefers 8123)
    python run.py 9000       # try 9000 first, then auto-detect

On startup it also **self-heals a broken or incomplete library install** - a
common symptom on corporate networks is:
    ImportError: cannot import name 'BaseModel' from 'pydantic' (unknown location)
which happens when a previous `pip install` was interrupted. The launcher
detects that, reinstalls the affected libraries, and reloads automatically.
"""
import os
import socket
import subprocess
import sys
import webbrowser

# Keep this list in sync with PORT_CANDIDATES in frontend/app.js
PORT_CANDIDATES = [8123, 8200, 8456, 8765, 9000, 9123, 9456, 7123, 7777, 10123]

_TRUSTED = ["--trusted-host", "pypi.org",
            "--trusted-host", "files.pythonhosted.org",
            "--trusted-host", "pypi.python.org"]


# --- dependency self-heal --------------------------------------------------

def _deps_ok() -> bool:
    """True if the core libraries import cleanly."""
    try:
        from pydantic import BaseModel  # noqa: F401 - the import that breaks
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except Exception:
        return False


def _pip_install(*args) -> int:
    return subprocess.call([sys.executable, "-m", "pip", "install", *args])


def ensure_deps() -> None:
    """If core libraries are missing/corrupted, repair them once, then reload."""
    if _deps_ok():
        return

    if os.environ.get("JM_REPAIRED") == "1":
        # We already tried repairing in a previous launch - give clear guidance.
        print("\n[!] Could not repair the libraries automatically.")
        print("    In PowerShell (with the .venv active) run:")
        print("      pip install --force-reinstall --no-cache-dir -r requirements.txt")
        print("    If your network blocks downloads, add:")
        print("      --trusted-host pypi.org --trusted-host files.pythonhosted.org")
        sys.exit(1)

    print("Some libraries look broken or incomplete - repairing (one-time, "
          "please wait)...")
    here = os.path.dirname(os.path.abspath(__file__))
    req = os.path.join(here, "requirements.txt")

    # 1) Make sure everything in requirements is present (retry for SSL proxies).
    if _pip_install("-r", req) != 0:
        _pip_install("-r", req, *_TRUSTED)

    # 2) Force-reinstall the usual culprit (a corrupted pydantic / pydantic-core).
    culprits = ["pydantic", "pydantic-core", "fastapi"]
    if _pip_install("--upgrade", "--force-reinstall", "--no-cache-dir",
                    *culprits) != 0:
        _pip_install("--upgrade", "--force-reinstall", "--no-cache-dir",
                     *culprits, *_TRUSTED)

    os.environ["JM_REPAIRED"] = "1"
    print("Reloading...")
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except Exception:
        print("Repair finished. Please start the app again.")
        sys.exit(0)


# --- port selection --------------------------------------------------------

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
    ensure_deps()

    preferred = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    port = pick_port(preferred)
    url = f"http://127.0.0.1:{port}"

    if port != preferred:
        print(f"Preferred port {preferred} was unavailable - "
              f"searched and found a working port.")
    print("=" * 60)
    print(f"  Jira Manager is running at:  {url}")
    print("  Open that address in your browser (Ctrl+C to stop).")
    print("=" * 60)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False)
