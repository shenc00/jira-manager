"""Send the monthly report through the user's local Outlook desktop app.

Uses Outlook COM automation (via pywin32), so it relies on the already
signed-in Outlook profile - no SMTP server or password is needed. Windows +
Outlook desktop only.
"""
from __future__ import annotations

import os


def send_via_outlook(to: str, subject: str, body: str,
                     attachment_path: str) -> None:
    """Send an email with an attachment via the default Outlook profile.

    Raises RuntimeError with a clear message if pywin32/Outlook isn't available.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pywin32 not installed
        raise RuntimeError(
            "pywin32 is not installed. In PowerShell (with .venv active) run: "
            "pip install pywin32") from exc

    # FastAPI runs sync endpoints on worker threads; COM needs initialising there.
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        if attachment_path:
            mail.Attachments.Add(os.path.abspath(attachment_path))
        mail.Send()
    except Exception as exc:  # noqa: BLE001 - surface a readable error
        raise RuntimeError(
            f"Outlook could not send the email ({exc}). Make sure the Outlook "
            "desktop app is installed and signed in.") from exc
    finally:
        pythoncom.CoUninitialize()
