"""Launch the Jira Manager web app.

    python run.py

Then open http://127.0.0.1:8000 in your browser.
"""
import webbrowser

import uvicorn

if __name__ == "__main__":
    url = "http://127.0.0.1:8000"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"Jira Manager running at {url}  (Ctrl+C to stop)")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
