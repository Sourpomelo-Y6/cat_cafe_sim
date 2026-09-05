# 猫カフェシミュレーター

Docsの仕様に基づく、1日営業シミュレーターとPhase 2の接客環境です。
営業CLIはPython標準ライブラリだけで動作します。接客環境には任意依存のGymnasiumを使用します。
Python 3.12で動作確認しています。プロジェクトのルートから実行してください。

```bash
# 固定方策による1日営業。JSONログと同名のCSV集計を保存
python3 -m cat_cafe_sim run --seed 42 --output reports/day.json

# 保存した設定・操作・猫行動で再実行し、全tickの状態とイベントを照合
python3 -m cat_cafe_sim replay reports/day.json

# ランダム猫方策（seedで再現可能）
python3 -m cat_cafe_sim run --policy random --seed 42 --output reports/random.json

# 境界条件・会計・再現性のテスト
python3 -m unittest discover -s tests -v
```

暫定値は `config/default.json` に集約しています。別のJSONを `--config` で指定できます。
猫の体力・気力、7行動の効果と消耗、固定来店時刻、客の好み、営業時間、料金、待機上限を変更できます。

コードは `cat_cafe_sim/core`（状態遷移）、`policies`（猫・店長の固定方策）、
`replay`（保存・再実行）、`__main__.py`（CLI）に分離しています。
店長は `Command("assign", "guest-1")` または `Command("wait")` を送り、
猫行動は方策が自動選択します。UIや学習ライブラリは必須ではありません。

実装範囲と判定規則、検証結果、今後の作業は [Docs/Phase1_ImplementationStatus.md](Docs/Phase1_ImplementationStatus.md) を参照してください。

Phase 2では、交流種類ごとの飽き・条件付き切り替えボーナスと、単一接客用の
`CatInteractionEnv`を追加しました。Q学習は次の実装段階です。

```bash
# 接客環境用の依存をインストール
venv/bin/python -m pip install -r requirements-env.txt

# Gymnasium公式チェッカーを含む全テスト
venv/bin/python -m unittest discover -s tests -v

# 連打・固定ループ・休む行動を、3種類の好みで比較
venv/bin/python -m cat_cafe_sim.envs --seed 42
```

Gymnasium未導入の場合、接客環境のテストのみスキップされます。
ルール・報酬設定、API使用例、診断結果は
[Docs/Phase2_InteractionFoundation.md](Docs/Phase2_InteractionFoundation.md)を参照してください。
0.2.0ではログ形式を拡張したため、0.1.0の営業ログは再生対象外です。
