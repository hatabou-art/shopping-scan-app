"""食品の写真から鮮度を判定する（Claude の画像解析を使う）。

コマンドラインからも使える:
    python3 freshness.py photo.jpg
"""

import base64
import json
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
あなたはスーパーの青果・鮮魚・精肉売り場で長年働いてきた目利きです。
買い物客が売り場で撮った写真を見て、食品の鮮度を判定します。

判定のしかた:
- 写真に写っている食品を特定し、その食品に固有の鮮度の目安で判断する
  （例: 魚は目の澄み具合・エラの色・身のハリ、葉物は葉先のしおれや変色、
   果物は皮のハリ・傷・カビ、肉はドリップや変色）。
- 写真から実際に見えた特徴だけを根拠に挙げる。見えないもの（匂い・硬さ・
  裏側）は推測で断定せず、「確認すると良い点」に回す。
- 写真が暗い・ぼやけている・食品が写っていないなどで判断できないときは、
  無理に点数を付けず grade を「判定不能」にし、撮り直し方を tips に書く。
- score は 0〜100（100 が最も新鮮）。目安: 80以上=新鮮、60〜79=良好、
  40〜59=早めに消費、40未満=避けたほうが良い。
- 日本語で、売り場で読んですぐ分かる短い文にする。
"""


class FreshnessResult(BaseModel):
    food: str = Field(description="写っている食品の名前（例: サバ、ほうれん草）")
    category: Literal["野菜", "果物", "魚介", "肉", "その他", "不明"]
    score: int = Field(description="鮮度スコア 0〜100。判定不能なら 0")
    grade: Literal["新鮮", "良好", "早めに消費", "避けたほうが良い", "判定不能"]
    summary: str = Field(description="ひとことの総評")
    observations: list[str] = Field(description="写真から見えた根拠")
    check_points: list[str] = Field(description="手に取って確認すると良い点")
    tips: list[str] = Field(description="保存方法・食べ方・撮り直し方などのアドバイス")


def judge(image_bytes: bytes, media_type: str, client: anthropic.Anthropic | None = None) -> FreshnessResult:
    client = client or anthropic.Anthropic()
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {"type": "text", "text": "この食品の鮮度を判定してください。"},
            ],
        }],
        output_format=FreshnessResult,
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("この画像は判定できませんでした。別の写真でお試しください。")
    if response.parsed_output is None:
        raise RuntimeError(f"判定結果を読み取れませんでした (stop_reason={response.stop_reason})")
    return response.parsed_output


MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp", ".gif": "image/gif"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        print(f"対応していない画像形式です: {path.suffix}", file=sys.stderr)
        return 2
    result = judge(path.read_bytes(), media_type)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
