#!/usr/bin/env python3
"""更新日時がいちばん新しい1本だけを残し、残りをゴミ箱へ移す。

既定は**ドライラン**で、何も消さずに一覧を出すだけ。中身を確認してから
--apply を付けて実行する。--apply でもゴミ箱に移すだけなので元に戻せる。

例:
    # まず確認（何も変更しない）
    python3 keep_latest.py ~/Documents --glob '*浦和*.xlsx'

    # 納得したら実行（最新1本以外をゴミ箱へ）
    python3 keep_latest.py ~/Documents --glob '*浦和*.xlsx' --apply

    # サブフォルダも含める
    python3 keep_latest.py ~/Documents --glob '*浦和*.xlsx' --recursive
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def trash_dir(sample: Path) -> Path:
    """書き込めるゴミ箱を返す。~/.Trash が使えなければ同階層に退避先を作る。"""
    home_trash = Path.home() / ".Trash"
    if home_trash.is_dir():
        probe = home_trash / ".keep_latest_write_test"
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
    ap.add_argument(
        "--glob",
        default="*.xlsx",
        help="対象のファイル名パターン (既定: *.xlsx)",
    )
    ap.add_argument("--recursive", action="store_true", help="サブフォルダも対象")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="実際に移動する。付けない限り何も変更しない",
    )
    args = ap.parse_args()

    root = args.directory.expanduser()
    if not root.is_dir():
        raise SystemExit(f"フォルダが見つかりません: {root}")

    finder = root.rglob if args.recursive else root.glob
    files = [p for p in finder(args.glob) if p.is_file()]
    # 一時ファイル・ロックファイルは対象外
    files = [p for p in files if not p.name.startswith(("~$", "."))]

    if not files:
        raise SystemExit(f"該当ファイルがありません: {root}/{args.glob}")

    # 更新日時の新しい順
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keep, remove = files[0], files[1:]

    print(f"対象フォルダ: {root}")
    print(f"パターン    : {args.glob}  (該当 {len(files)} 件)\n")
    for i, p in enumerate(files):
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        mark = "残す  " if i == 0 else "ゴミ箱"
        print(f"  [{mark}] {mtime}  {human_size(st.st_size):>8}  {p.name}")

    if not remove:
        print("\n該当が1件だけなので、何もすることがありません。")
        return 0

    if not args.apply:
        print(
            f"\nドライランです。何も変更していません。"
            f"\n上記の判定でよければ --apply を付けて再実行してください。"
        )
        return 0

    dest_dir = trash_dir(keep)
    moved = 0
    for p in remove:
        dest = unique_dest(dest_dir, p.name)
        try:
            shutil.move(str(p), str(dest))
        except OSError as exc:
            print(f"  [失敗] {p.name}: {exc}", file=sys.stderr)
            continue
        moved += 1

    print(f"\n{moved} 件を {dest_dir} に移しました。")
    print(f"残したファイル: {keep}")
    if moved != len(remove):
        print(f"移せなかったファイルが {len(remove) - moved} 件あります。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
