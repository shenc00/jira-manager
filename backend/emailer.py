"""Send the monthly report through the user's local Outlook desktop app.

Uses Outlook COM automation (via pywin32), so it relies on the already
signed-in Outlook profile - no SMTP server or password is needed. The email is
sent *as the user* (their default Outlook account). Windows + Outlook only.
"""
from __future__ import annotations

import os


def send_via_outlook(to: str, subject: str, body: str,
                     attachment_path: str, display: bool = False) -> str:
    """Send (or, if ``display``, just open) an email with an attachment via the
    default Outlook profile. Returns the sender's email address.

    ``display=True`` opens the composed email in Outlook for the user to review
    and click Send themselves - more reliable when silent send is blocked.

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
        sender = ""
        try:
            sender = outlook.Session.Accounts.Item(1).SmtpAddress
        except Exception:  # noqa: BLE001
            try:
                sender = outlook.Session.CurrentUser.Address
            except Exception:  # noqa: BLE001
                sender = ""

        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        if attachment_path:
            mail.Attachments.Add(os.path.abspath(attachment_path))

        if display:
            mail.Display(False)  # open the draft; the user reviews and sends
        else:
            mail.Send()
            # Send() only queues to the Outbox; nudge a send/receive so it
            # actually goes out even if Outlook was idle.
            try:
                for sync in outlook.GetNamespace("MAPI").SyncObjects:
                    sync.Start()
            except Exception:  # noqa: BLE001 - best effort
                pass
        return sender
    except Exception as exc:  # noqa: BLE001 - surface a readable error
        verb = "open" if display else "send"
        raise RuntimeError(
            f"Outlook could not {verb} the email ({exc}). Make sure the Outlook "
            "desktop app is installed and signed in.") from exc
    finally:
        pythoncom.CoUninitialize()
