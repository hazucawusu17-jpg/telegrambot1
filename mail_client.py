import imaplib
import email
import os
import re
from email.header import decode_header
from email.utils import parseaddr
from dotenv import load_dotenv

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "INBOX")


def _decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            decoded.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(raw)
    return "".join(decoded)


def _strip_html(html):
    clean = re.sub(r"<[^>]+>", "", html)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace").strip()
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                raw = part.get_payload(decode=True).decode(charset, errors="replace")
                return _strip_html(raw)
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="replace").strip()
        if msg.get_content_type() == "text/html":
            return _strip_html(body)
        return body
    return ""


def fetch_latest_email_for_address(target_email):
    """
    Search the catch-all IMAP inbox for the most recent email
    addressed TO target_email (checks To, Cc, Delivered-To headers).
    Returns dict(sender, date, subject, body) or None.
    """
    target_email = target_email.lower().strip()

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as mail:
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select(IMAP_MAILBOX, readonly=True)

        # Try server-side TO search first
        status, data = mail.search(None, f'TO "{target_email}"')
        if status == "OK" and data[0]:
            uids = data[0].split()
        else:
            # Fallback: client-side filter over all messages
            status, data = mail.search(None, "ALL")
            if status != "OK" or not data[0]:
                return None
            uids = data[0].split()

        for uid in reversed(uids):
            status, msg_data = mail.fetch(uid, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            recipients = []
            for header in ("To", "Cc", "Delivered-To", "X-Original-To"):
                val = msg.get(header, "")
                for addr in val.split(","):
                    _, email_addr = parseaddr(addr.strip())
                    if email_addr:
                        recipients.append(email_addr.lower())

            if target_email not in recipients:
                continue

            return {
                "sender":  _decode_str(msg.get("From", "")),
                "date":    msg.get("Date", "Unknown"),
                "subject": _decode_str(msg.get("Subject", "(no subject)")),
                "body":    _get_body(msg),
            }

    return None
