"""Launch the Jira Manager web app.

    python run.py            # uses port 8123
    python run.py 9000       # use a different port if 8123 is busy

Then open http://127.0.0.1:<port> in your browser.
"""
import sys
import webbrowser

import uvicorn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    url = f"http://127.0.0.1:{port}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"Jira Manager running at {url}  (Ctrl+C to stop)")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False)
