# 鮮度チェッカー

売り場で食品（野菜・果物・魚・肉）をスマホで撮影すると、Claude が写真の見た目から
鮮度を 0〜100 点と 5 段階（新鮮 / 良好 / 早めに消費 / 避けたほうが良い / 判定不能）で判定し、
根拠・手に取って確認したい点・保存のアドバイスを表示します。

## 使い方

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # または `ant auth login`
python3 server.py                   # http://localhost:8000
```

同じ Wi-Fi のスマホから使う場合は `python3 server.py --host 0.0.0.0` で起動し、
`http://<PCのIP>:8000` を開きます（「撮影して判定」ボタンは HTTP でもカメラが起動します）。

コマンドラインで1枚だけ判定することもできます:

```sh
python3 freshness.py photo.jpg
```

## 構成

| ファイル | 役割 |
|---|---|
| `freshness.py` | 画像を Claude (claude-opus-5-5) に送り、構造化された判定結果を返す |
| `server.py` | 画面の配信と `POST /api/judge`（画像を受け取り判定結果の JSON を返す） |
| `static/index.html` | スマホ向け画面。撮影 → 縮小（長辺1568px）→ 送信 → 結果表示 |

判定は写真の見た目による目安です。匂い・硬さ・消費期限は別途確認してください。
