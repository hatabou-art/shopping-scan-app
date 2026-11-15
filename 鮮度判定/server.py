#!/usr/bin/env python3
"""鮮度判定アプリの Web サーバー。

スマホのブラウザで開き、カメラで食品を撮ると鮮度を判定して表示する。

例:
    export ANTHROPIC_API_KEY=...
    python3 server.py              # http://localhost:8000
    python3 server.py --port 8080 --host 0.0.0.0   # 同じ Wi-Fi のスマホから開く

注意: スマホのブラウザでカメラを使うには HTTPS か localhost が必要。
LAN 越しに使うときは画像ファイル選択（撮影）ボタンなら HTTP でも動く。
"""

import argparse
import json
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

from freshness import judge

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD = 10 * 1024 * 1024  # 10MB
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

client = anthropic.Anthropic()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/judge":
            self.send_json(404, {"error": "not found"})
            return

        media_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        if media_type not in ALLOWED_TYPES:
            self.send_json(415, {"error": "JPEG / PNG / WebP / GIF の画像を送ってください"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            self.send_json(413, {"error": "画像が大きすぎるか空です（10MBまで）"})
            return

        try:
            result = judge(self.rfile.read(length), media_type, client)
        except anthropic.RateLimitError:
            self.send_json(429, {"error": "混み合っています。少し待ってからもう一度お試しください"})
        except anthropic.APIStatusError as e:
            logging.exception("API error")
            self.send_json(502, {"error": f"判定サービスでエラーが起きました ({e.status_code})"})
        except anthropic.APIConnectionError:
            self.send_json(502, {"error": "判定サービスに接続できませんでした"})
        except RuntimeError as e:
            self.send_json(422, {"error": str(e)})
        else:
            self.send_json(200, result.model_dump())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"http://{args.host}:{args.port} で起動しました（Ctrl+C で終了）")
    server.serve_forever()


if __name__ == "__main__":
    main()
