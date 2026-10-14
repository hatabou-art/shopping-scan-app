#!/usr/bin/env python3
"""netkeiba(地方競馬) の data_list ページからデータ表を取得して CSV に落とす。

トリプル馬単の対象は「最終レースからさかのぼる3レース」で、開催日ごとに
レース数が違う (10R制の日は 8R-10R、12R制の日は 10R-12R)。--final-race に
その日の最終レース番号を渡すこと。

例:
    # 大井 2026/08/15 は10R制 -> 8R/9R/10R
    python3 fetch_netkeiba_data_list.py --track 大井 --date 2026-08-15 --final-race 10

    # R を明示指定
    python3 fetch_netkeiba_data_list.py --track 川崎 --date 2026-08-17 --races 10 11 12

    # race_id を直接指定
    python3 fetch_netkeiba_data_list.py 202644081508 --page shutuba

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

PAGES = {
    "data_list": "https://nar.netkeiba.com/race/data_list.html",
    "shutuba": "https://nar.netkeiba.com/race/shutuba.html",
}
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

TRACK_CODES = {
    "門別": "30", "盛岡": "35", "水沢": "36", "浦和": "42", "船橋": "43",
    "大井": "44", "川崎": "45", "金沢": "46", "笠松": "47", "名古屋": "48",
    "園田": "50", "姫路": "51", "高知": "54", "佐賀": "55", "帯広": "65",
}



def triple_umatan_races(final_race: int) -> list:
    """トリプル馬単の対象は最終レースからさかのぼる3レース。

    開催日ごとにレース数が違うので、最終レース番号から導く必要がある。
    10R制なら 8R-10R、12R制なら 10R-12R。
    """
    if final_race < 3:
        raise SystemExit(f"最終レースが {final_race}R では対象3レースを取れません")
    return [final_race - 2, final_race - 1, final_race]


def build_race_ids(track: str, date: str, races) -> list:
    """競馬場名・日付(YYYY-MM-DD or YYYYMMDD)・R番号から race_id を組み立てる。"""
    if track not in TRACK_CODES:
        raise SystemExit(
            f"未知の競馬場: {track} (指定可能: {'/'.join(TRACK_CODES)})"
        )
    ymd = date.replace("-", "").replace("/", "")
    if not re.fullmatch(r"\d{8}", ymd):
        raise SystemExit(f"日付は YYYY-MM-DD 形式で指定してください: {date}")
    return [f"{ymd[:4]}{TRACK_CODES[track]}{ymd[4:]}{int(r):02d}" for r in races]


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


def fetch(race_id: str, mode: str, cid: str, page: str = "data_list") -> str:
    base = PAGES[page]
    url = f"{base}?race_id={race_id}"
    if page == "data_list":
        url += f"&mode={mode}&cid={cid}"
    req = Request(url, headers={"User-Agent": UA, "Referer": base})
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
    ap.add_argument("race_ids", nargs="*")
    ap.add_argument("--track", help="競馬場名 (例: 大井)。--date と併用")
    ap.add_argument("--date", help="開催日 YYYY-MM-DD。--track と併用")
    ap.add_argument("--races", nargs="+", help="取得する R 番号を明示指定")
    ap.add_argument(
        "--final-race",
        type=int,
        help="その開催日の最終レース番号。トリプル馬単の対象3レースを自動算出する"
        " (例: --final-race 10 なら 8R/9R/10R)",
    )
    ap.add_argument("--page", default="data_list", choices=sorted(PAGES))
    ap.add_argument("--mode", default="others")
    ap.add_argument("--cid", default="0")
    ap.add_argument("--out", default=".", type=Path)
    ap.add_argument("--sleep", default=1.0, type=float, help="リクエスト間隔(秒)")
    args = ap.parse_args()

    if bool(args.track) != bool(args.date):
        raise SystemExit("--track と --date は両方セットで指定してください")
    if args.races and args.final_race:
        raise SystemExit("--races と --final-race はどちらか一方にしてください")

    if args.track:
        if args.final_race:
            races = triple_umatan_races(args.final_race)
        elif args.races:
            races = args.races
        else:
            raise SystemExit(
                "--races か --final-race を指定してください。"
                " トリプル馬単の対象は最終レースからさかのぼる3レースで、"
                " 開催日ごとにレース数が異なります"
                " (例: 10R制の日は --final-race 10 で 8R/9R/10R)"
            )
        race_ids = build_race_ids(args.track, args.date, races)
    elif args.race_ids:
        race_ids = args.race_ids
    else:
        raise SystemExit("race_id、または --track と --date を指定してください")

    args.out.mkdir(parents=True, exist_ok=True)
    failed = []

    for i, race_id in enumerate(race_ids):
        if i:
            time.sleep(args.sleep)
        try:
            html = fetch(race_id, args.mode, args.cid, args.page)
        except Exception as exc:
            print(f"[NG] {race_id}: {exc}", file=sys.stderr)
            failed.append(race_id)
            continue

        stem = f"{race_id}_{args.page}_{args.mode}"
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
