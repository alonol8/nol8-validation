import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import re

RE_EMAIL = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
RE_SSN = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
RE_PHONE = re.compile(r"\b(\d{3})-(\d{3})-(\d{4})\b")
RE_ACCOUNT = re.compile(r"\bACC-\d{4}-\d{4}\b")
RE_HEADER = re.compile(r"(?im)^Welcome to .*")
RE_NAV = re.compile(r"(?im)^Navigation:.*")
RE_FOOTER = re.compile(r"(?im)^Footer:.*")
RE_DISCLAIMER = re.compile(r"(?im)^Legal Disclaimer:.*")
RE_COOKIE = re.compile(r"(?im)^Cookie Notice:.*")

def clean_blank_lines(text: str) -> str:
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join([line for line in lines if line])

def process_text(text: str):
    original = text
    text = RE_EMAIL.sub(r"[MASKED]@\2", text)
    text = RE_SSN.sub(r"XXX-XX-\3", text)
    text = RE_PHONE.sub(r"XXX-XXX-\3", text)
    text = RE_ACCOUNT.sub(r"[MASKED_ACCOUNT_ID]", text)
    text = RE_HEADER.sub("", text)
    text = RE_NAV.sub("", text)
    text = RE_FOOTER.sub("", text)
    text = RE_DISCLAIMER.sub("", text)
    text = RE_COOKIE.sub("", text)
    text = clean_blank_lines(text)

    if not text.strip():
        return {"action": "drop", "text": ""}

    lower = text.lower()
    if "confidential" in lower and "elastic" not in lower:
        return {"action": "route", "text": text}

    if text != original:
        return {"action": "mask", "text": text}

    return {"action": "keep", "text": text}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/process":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        result = process_text(payload.get("text", ""))
        body = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8787), Handler)
    print("Mock Nol8 server listening on http://127.0.0.1:8787/process")
    server.serve_forever()
