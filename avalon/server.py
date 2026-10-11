import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).parent.parent / "web" / "index.html"


def serve(runs_dir, port):
    runs = Path(runs_dir)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, body, ctype, status=200):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self.reply(PAGE.read_text(), "text/html; charset=utf-8")
            elif path == "/api/games":
                logs = sorted(runs.glob("*/game.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                self.reply(json.dumps([f.parent.name for f in logs]), "application/json")
            elif path.startswith("/api/games/"):
                log = runs / path.removeprefix("/api/games/") / "game.jsonl"
                if log.parent.parent == runs and log.is_file():
                    self.reply(log.read_text(), "application/x-ndjson")
                else:
                    self.reply("not found", "text/plain", 404)
            else:
                self.reply("not found", "text/plain", 404)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving {runs} at http://127.0.0.1:{port}")
    server.serve_forever()
