#!/usr/bin/env python3
"""netkeiba(地方競馬)のオッズを取得してスナップショットに残し、人気の変化を出す。

同じコマンドを時間をおいて何度か実行すると、2回目以降は前回との差分
(人気の上下・オッズの変動率)を表示する。トリプル馬単の対象3レースを
締切前に何度か叩いて、支持の動きを見るための道具。

例:
    # 1回目(基準を取る)
    python3 track_odds.py --track 川崎 --date 2026-11-12 --final-race 12

    # しばらく置いて2回目以降(前回との差分が出る)
    python3 track_odds.py --track 川崎 --date 2026-11-12 --final-race 12

    # race_id を直接指定
    python3 track_odds.py 202645111210 202645111211 202645111212

オッズAPIの注意点(船橋ルーチンの知見):
  - odds_status が "yoso" のものは発売前の予想オッズなので使わない
  - odds_status が "real" でも全馬の Odds が "0.0" のことがある
    (発売直後でまだ入金なし)。この場合も人気順は意味を持たない
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ODDS_API = "https://nar.netkeiba.com/api/api_get_nar_odds.html"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

TRACK_CODES = {
    "門別": "30", "盛岡": "35", "水沢": "36", "浦和": "42", "船橋": "43",
    "大井": "44", "川崎": "45", "金沢": "46", "笠松": "47", "名古屋": "48",
    "園田": "50", "姫路": "51", "高知": "54", "佐賀": "55", "帯広": "65",
}


def build_race_ids(track: str, date: str, races) -> list:
    if track not in TRACK_CODES:
        raise SystemExit(f"未知の競馬場: {track} (指定可能: {'/'.join(TRACK_CODES)})")
    ymd = date.replace("-", "").replace("/", "")
    if not re.fullmatch(r"\d{8}", ymd):
        raise SystemExit(f"日付は YYYY-MM-DD 形式で指定してください: {date}")
    return [f"{ymd[:4]}{TRACK_CODES[track]}{ymd[4:]}{int(r):02d}" for r in races]


def triple_umatan_races(final_race: int) -> list:
    """トリプル馬単の対象は最終レースからさかのぼる3レース。"""
    if final_race < 3:
        raise SystemExit(f"最終レースが {final_race}R では対象3レースを取れません")
    return [final_race - 2, final_race - 1, final_race]


def fetch_odds(race_id: str) -> dict:
    url = f"{ODDS_API}?race_id={race_id}&type=1"
    req = Request(url, headers={"User-Agent": UA, "Referer": ODDS_API})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_entries(payload: dict) -> tuple:
    """(状態, [{umaban, odds, ninki}]) を返す。使えない場合は状態に理由。"""
    status = str(payload.get("odds_status", "")).lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw = data.get("ary_odds") or data.get("odds") or []
    if isinstance(raw, dict):
        raw = list(raw.values())

    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        umaban = item.get("Umaban") or item.get("umaban") or item.get("Num")
        odds = item.get("Odds") or item.get("odds")
        ninki = item.get("Ninki") or item.get("ninki")
        try:
            odds_f = float(odds)
        except (TypeError, ValueError):
            odds_f = None
        try:
            ninki_i = int(ninki)
        except (TypeError, ValueError):
            ninki_i = None
        if umaban is None:
            continue
        entries.append({
            "umaban": str(umaban).lstrip("0") or "0",
            "odds": odds_f,
            "ninki": ninki_i,
        })

    if not entries:
        return "出走データなし", []
    if status == "yoso":
        return "発売前の予想オッズ(yoso)のため使用しない", entries
    if all((e["odds"] or 0) == 0 for e in entries):
        return "全馬オッズ0.0(発売直後で入金なし)のため人気順は無意味", entries
    return "ok", entries


def snapshot_path(dirpath: Path, race_id: str, stamp: str) -> Path:
    return dirpath / f"{race_id}_{stamp}.json"


def previous_snapshots(dirpath: Path, race_id: str) -> list:
    return sorted(dirpath.glob(f"{race_id}_*.json"))


def fmt_odds(v) -> str:
    return "-" if v in (None, 0) else f"{v:.1f}"


def show_diff(race_id: str, now_entries: list, prev_file: Path) -> None:
    try:
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  前回分を読めません ({prev_file.name}): {exc}")
        return
    prev_map = {e["umaban"]: e for e in prev.get("entries", [])}
    prev_at = prev.get("fetched_at_jst", prev_file.stem.split("_")[-1])

    print(f"  前回: {prev_at}")
    print(f"  {'馬番':>4} {'人気':>5} {'前回':>5} {'変化':>5} "
          f"{'オッズ':>7} {'前回':>7} {'変動':>8}")
    rows = sorted(now_entries, key=lambda e: (e["ninki"] is None, e["ninki"] or 999))
    for e in rows:
        p = prev_map.get(e["umaban"])
        if not p:
            print(f"  {e['umaban']:>4} {str(e['ninki'] or '-'):>5} {'新':>5} "
                  f"{'':>5} {fmt_odds(e['odds']):>7} {'-':>7} {'-':>8}")
            continue
        # 人気は小さいほど上位。前回-今回 が正なら人気が上がった
        if e["ninki"] and p.get("ninki"):
            d = p["ninki"] - e["ninki"]
            move = f"+{d}" if d > 0 else (str(d) if d < 0 else "±0")
        else:
            move = "-"
        if e["odds"] and p.get("odds"):
            pct = (e["odds"] - p["odds"]) / p["odds"] * 100
            chg = f"{pct:+.1f}%"
        else:
            chg = "-"
        print(f"  {e['umaban']:>4} {str(e['ninki'] or '-'):>5} "
              f"{str(p.get('ninki') or '-'):>5} {move:>5} "
              f"{fmt_odds(e['odds']):>7} {fmt_odds(p.get('odds')):>7} {chg:>8}")
    print("  ※ 変化の + は人気が上がった(支持が集まった)、- は下がった")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_ids", nargs="*")
    ap.add_argument("--track", help="競馬場名 (例: 川崎)。--date と併用")
    ap.add_argument("--date", help="開催日 YYYY-MM-DD。--track と併用")
    ap.add_argument("--races", nargs="+", help="取得する R 番号を明示指定")
    ap.add_argument("--final-race", type=int,
                    help="その開催日の最終レース番号。対象3レースを自動算出")
    ap.add_argument("--snapshot-dir", default="odds_snapshots", type=Path)
    ap.add_argument("--sleep", default=1.0, type=float)
    ap.add_argument("--no-save", action="store_true",
                    help="取得するが記録しない(差分の基準を汚さない)")
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
                "--races か --final-race を指定してください。トリプル馬単の対象は"
                " 最終レースからさかのぼる3レースで、開催日ごとにレース数が異なります"
            )
        race_ids = build_race_ids(args.track, args.date, races)
    elif args.race_ids:
        race_ids = args.race_ids
    else:
        raise SystemExit("race_id、または --track と --date を指定してください")

    args.snapshot_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    failed = []

    for i, race_id in enumerate(race_ids):
        if i:
            time.sleep(args.sleep)
        print(f"\n=== {race_id} ===")
        try:
            payload = fetch_odds(race_id)
        except Exception as exc:
            print(f"  取得失敗: {exc}")
            failed.append(race_id)
            continue

        state, entries = parse_entries(payload)
        if state != "ok":
            print(f"  使用不可: {state}")
            failed.append(race_id)
            continue

        prevs = previous_snapshots(args.snapshot_dir, race_id)
        print(f"  取得: {now.strftime('%Y-%m-%d %H:%M:%S')}  {len(entries)}頭")
        if prevs:
            show_diff(race_id, entries, prevs[-1])
        else:
            print("  初回取得のため差分なし。時間をおいて再実行すると変化が出ます")
            for e in sorted(entries,
                            key=lambda x: (x["ninki"] is None, x["ninki"] or 999)):
                print(f"  {e['umaban']:>4}番  {str(e['ninki'] or '-'):>3}人気  "
                      f"{fmt_odds(e['odds']):>7}倍")

        if not args.no_save:
            out = snapshot_path(args.snapshot_dir, race_id, stamp)
            out.write_text(json.dumps({
                "race_id": race_id,
                "fetched_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
                "entries": entries,
            }, ensure_ascii=False, indent=1), encoding="utf-8")

    if failed:
        print(f"\n使えなかったレース: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
