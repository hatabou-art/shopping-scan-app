"""字幕読み上げの画面を配信する小さなサーバ。

スマホのブラウザでカメラを使うには HTTPS が必要なため、--https を付けると
自己署名証明書を作って HTTPS で配信します（初回アクセス時に警告が出るので「詳細」→「進む」）。
"""
import argparse
import functools
import http.server
import socket
import ssl
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CERT_DIR = HERE / ".cert"


def make_cert() -> tuple[Path, Path]:
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if not cert.exists():
        CERT_DIR.mkdir(exist_ok=True)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
             "-subj", "/CN=subtitle-reader", "-keyout", str(key), "-out", str(cert)],
            check=True, capture_output=True,
        )
    return cert, key


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--https", action="store_true", help="自己署名証明書で HTTPS 配信する（スマホ用）")
    args = ap.parse_args()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    scheme = "http"
    if args.https:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*make_cert())
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    host = lan_ip() if args.host == "0.0.0.0" else args.host
    print(f"{scheme}://{host}:{args.port}/ で開いてください（Ctrl+C で終了）")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
