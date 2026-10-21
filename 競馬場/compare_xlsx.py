#!/usr/bin/env python3
"""同名違いの .xlsx を「名前」と「中身」で比較し、残す1本を判断する。

更新日時は一切見ない。アップロードやコピーで日時が壊れていても使える。
標準ライブラリだけで動く（openpyxl 不要）。

既定は比較表を出すだけで、何も削除しない。

例:
    # 比較して推奨を見る（変更なし）
    python3 compare_xlsx.py ~/Documents --glob '*浦和*.xlsx'

    # 推奨どおりに整理（残り1本以外をゴミ箱へ）
    python3 compare_xlsx.py ~/Documents --glob '*浦和*.xlsx' --apply

    # 残すファイルを自分で指定して整理
    python3 compare_xlsx.py ~/Documents --glob '*浦和*.xlsx' \
        --keep '20261021浦和_v3.xlsx' --apply
"""

import argparse
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DATE_RE = re.compile(r"(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})")

# 名前に出るバージョン語。大きいほど新しいとみなす。
NAME_MARKERS = [
    (re.compile(r"(?:最終|最新|final|latest)", re.I), 40, "最新語"),
    (re.compile(r"(?:修正|改訂|fix|rev)", re.I), 20, "修正語"),
    (re.compile(r"(?:コピー|copy|複製|backup|bak|旧|old)", re.I), -30, "複製・旧版語"),
]


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n


def name_signals(name: str) -> tuple:
    """ファイル名から (スコア, 根拠リスト) を返す。"""
    score, why = 0, []

    m = re.search(r"[vV](\d{1,3})\b", name)
    if m:
        score += 100 + int(m.group(1)) * 10
        why.append(f"v{m.group(1)}")

    m = re.search(r"\((\d{1,3})\)", name)
    if m:
        score += 50 + int(m.group(1)) * 5
        why.append(f"連番({m.group(1)})")

    dates = DATE_RE.findall(name)
    if dates:
        latest = max("".join(d) for d in dates)
        score += 10
        why.append(f"名前の日付 {latest}")

    m = re.search(r"\b([01]\d|2[0-3])[:_]?([0-5]\d)\b", name)
    if m:
        why.append(f"名前の時刻 {m.group(1)}:{m.group(2)}")

    for pat, pts, label in NAME_MARKERS:
        if pat.search(name):
            score += pts
            why.append(label)

    return score, why


def inspect(path: Path) -> dict:
    """.xlsx の中身を標準ライブラリで調べる。"""
    info = {
        "path": path,
        "size": path.stat().st_size,
        "sheets": [],
        "cells": 0,
        "max_row": 0,
        "strings": 0,
        "max_date": None,
        "error": None,
    }
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())

            if "xl/workbook.xml" in names:
                root = ET.fromstring(zf.read("xl/workbook.xml"))
                info["sheets"] = [
                    s.get("name", "?") for s in root.iter(f"{NS_MAIN}sheet")
                ]

            dates = []
            if "xl/sharedStrings.xml" in names:
                with zf.open("xl/sharedStrings.xml") as fh:
                    for _, el in ET.iterparse(fh, events=("end",)):
                        if el.tag == f"{NS_MAIN}si":
                            info["strings"] += 1
                            text = "".join(el.itertext())
                            for d in DATE_RE.findall(text):
                                dates.append("".join(d))
                            el.clear()
            if dates:
                info["max_date"] = max(dates)

            for member in sorted(n for n in names
                                 if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
                with zf.open(member) as fh:
                    for _, el in ET.iterparse(fh, events=("end",)):
                        if el.tag == f"{NS_MAIN}dimension":
                            ref = el.get("ref", "")
                            m = re.search(r":([A-Z]+)(\d+)$", ref)
                            if m:
                                info["max_row"] = max(info["max_row"], int(m.group(2)))
                            el.clear()
                        elif el.tag == f"{NS_MAIN}c":
                            if el.find(f"{NS_MAIN}v") is not None or \
                               el.find(f"{NS_MAIN}is") is not None:
                                info["cells"] += 1
                            el.clear()
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def trash_dir(sample: Path) -> Path:
    home_trash = Path.home() / ".Trash"
    if home_trash.is_dir():
        probe = home_trash / ".compare_xlsx_write_test"
        try:
            probe.touch()
            probe.unlink()
            return home_trash
        except OSError:
            pass
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fallback = sample.parent / f"_removed_{stamp}"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def unique_dest(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 1000):
        cand = dest_dir / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
    raise SystemExit(f"退避先の名前が決まりません: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", nargs="?", default=".", type=Path)
    ap.add_argument("--glob", default="*.xlsx", help="対象パターン (既定: *.xlsx)")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--keep", help="残すファイル名を明示指定する")
    ap.add_argument("--apply", action="store_true",
                    help="実際に整理する。付けない限り何も変更しない")
    args = ap.parse_args()

    root = args.directory.expanduser()
    if not root.is_dir():
        raise SystemExit(f"フォルダが見つかりません: {root}")

    finder = root.rglob if args.recursive else root.glob
    files = [p for p in finder(args.glob)
             if p.is_file() and not p.name.startswith(("~$", "."))]
    if not files:
        raise SystemExit(f"該当ファイルがありません: {root}/{args.glob}")

    infos = [inspect(p) for p in sorted(files)]
    for info in infos:
        info["name_score"], info["name_why"] = name_signals(info["path"].name)

    print(f"対象フォルダ: {root}")
    print(f"パターン    : {args.glob}  (該当 {len(infos)} 件)\n")
    print(f"{'ファイル名':<34} {'サイズ':>8} {'シート':>5} {'最終行':>6} "
          f"{'セル数':>7} {'中の最大日付':>12}")
    print("-" * 82)
    for info in infos:
        if info["error"]:
            print(f"{info['path'].name:<34} 読めません: {info['error']}")
            continue
        print(f"{info['path'].name:<34} {human_size(info['size']):>8} "
              f"{len(info['sheets']):>5} {info['max_row']:>6} "
              f"{info['cells']:>7} {info['max_date'] or '-':>12}")

    readable = [i for i in infos if not i["error"]]
    if not readable:
        raise SystemExit("\nどのファイルも読めませんでした。中身での判断ができません。")

    print("\n名前の手がかり:")
    for info in infos:
        why = "、".join(info["name_why"]) if info["name_why"] else "（手がかりなし）"
        print(f"  {info['path'].name}: {why}")

    # 中の最大日付 → セル数 → 名前スコア の優先順
    def rank(i):
        return (i["max_date"] or "", i["cells"], i["name_score"])

    recommended = max(readable, key=rank)
    print(f"\n推奨: {recommended['path'].name} を残す")
    basis = []
    if recommended["max_date"]:
        basis.append(f"中の最大日付が最も新しい({recommended['max_date']})")
    basis.append(f"データセル数 {recommended['cells']}")
    if recommended["name_why"]:
        basis.append("名前: " + "、".join(recommended["name_why"]))
    print("  根拠: " + " / ".join(basis))
    print("  ※ これは推定です。行数が多い方が新しいとは限りません"
          "（抜粋版や分割版の可能性があります）。表を必ず目で確認してください。")

    if args.keep:
        chosen = next((i for i in infos if i["path"].name == args.keep), None)
        if chosen is None:
            raise SystemExit(f"\n--keep で指定した名前が候補にありません: {args.keep}")
    else:
        chosen = recommended

    remove = [i for i in infos if i["path"] != chosen["path"]]
    if not remove:
        print("\n該当が1件だけなので、何もすることがありません。")
        return 0

    if not args.apply:
        print("\nドライランです。何も変更していません。")
        print("この判定でよければ --apply を付けて再実行してください。")
        print(f"別のファイルを残すなら --keep '<ファイル名>' --apply を指定してください。")
        return 0

    print(f"\n残す: {chosen['path'].name}")
    dest_dir = trash_dir(chosen["path"])
    moved = 0
    for info in remove:
        dest = unique_dest(dest_dir, info["path"].name)
        try:
            shutil.move(str(info["path"]), str(dest))
        except OSError as exc:
            print(f"  [失敗] {info['path'].name}: {exc}", file=sys.stderr)
            continue
        moved += 1
    print(f"{moved} 件を {dest_dir} に移しました。")
    if moved != len(remove):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
