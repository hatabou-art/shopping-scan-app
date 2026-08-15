#!/usr/bin/env python3
"""netkeiba(地方競馬) の data_list ページからデータ表を取得して CSV に落とす。

例:
    # 川崎 2026/08/17 10R-12R の mode=others を取得
    python3 fetch_netkeiba_data_list.py

    # race_id を明示
    python3 fetch_netkeiba_data_list.py 202645081710 202645081711

    # 別のタブ
    python3 fetch_netkeiba_data_list.py --mode others --out ./out

race_id = 年(4) + 場コード(2) + 月日(4) + R(2)
場コード: 30 門別 / 35 盛岡 / 36 水沢 / 42 浦和 / 43 船橋 / 44 大井 /
          45 川崎 / 46 金沢 / 47 笠松 / 48 名古屋 / 50 園田 / 51 姫路 /
          54 高知 / 55 佐賀 / 65 帯広ば
"""

import argparse
import csv
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://nar.netkeiba.com/race/data_list.html"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 川崎 2026/08/17 10R-12R
DEFAULT_RACE_IDS = ["202645081710", "202645081711", "202645081712"]


class TableParser(HTMLParser):
    """ページ中の <table> をすべて行列として拾う。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def detect_charset(raw: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type, re.I)
    if m:
        return m.group(1)
    m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4096], re.I)
    if m:
        return m.group(1).decode("ascii", "ignore")
    return "utf-8"


def fetch(race_id: str, mode: str, cid: str) -> str:
    url = f"{BASE}?race_id={race_id}&mode={mode}&cid={cid}"
    req = Request(url, headers={"User-Agent": UA, "Referer": BASE})
    with urlopen(req, timeout=30) as resp:
        raw = resp.read()
        charset = detect_charset(raw, resp.headers.get("Content-Type", ""))
    for enc in (charset, "utf-8", "euc-jp", "cp932"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_ids", nargs="*", default=DEFAULT_RACE_IDS)
    ap.add_argument("--mode", default="others")
    ap.add_argument("--cid", default="0")
    ap.add_argument("--out", default=".", type=Path)
    ap.add_argument("--sleep", default=1.0, type=float, help="リクエスト間隔(秒)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    race_ids = args.race_ids or DEFAULT_RACE_IDS
    failed = []

    for i, race_id in enumerate(race_ids):
        if i:
            time.sleep(args.sleep)
        try:
            html = fetch(race_id, args.mode, args.cid)
        except Exception as exc:
            print(f"[NG] {race_id}: {exc}", file=sys.stderr)
            failed.append(race_id)
            continue

        stem = f"{race_id}_{args.mode}"
        (args.out / f"{stem}.html").write_text(html, encoding="utf-8")

        parser = TableParser()
        parser.feed(html)
        # 最も行数の多い表を本体とみなす（ヘッダ・ナビの小さな表を避ける）
        tables = [t for t in parser.tables if len(t) > 1]
        if not tables:
            print(
                f"[!!] {race_id}: 表が見つかりません。"
                f" 表が JS で後読みされている可能性があります → {stem}.html を確認",
                file=sys.stderr,
            )
            failed.append(race_id)
            continue

        table = max(tables, key=len)
        csv_path = args.out / f"{stem}.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            csv.writer(fh).writerows(table)
        print(f"[OK] {race_id}: {len(table)} 行 -> {csv_path}")

    if failed:
        print(f"\n取得できなかった race_id: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
