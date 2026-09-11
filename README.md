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
`CatInteractionEnv`を追加しました。さらに離散化・Q学習・モデル保存と比較評価も利用できます。

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

猫方策の学習と評価：

```bash
venv/bin/python -m cat_cafe_sim.training inspect
venv/bin/python -m cat_cafe_sim.training train
venv/bin/python -m cat_cafe_sim.training evaluate --split test --output reports/cat_q.test.json
```

既定では3,000接客を学習し、`models/cat_q.json`と接客ごとのCSV・比較JSONを保存します。
学習・調整・評価の客条件を分け、保存前後の評価結果も照合します。
設定と検証結果は[Docs/Phase2_QLearning.md](Docs/Phase2_QLearning.md)を参照してください。

保存したモデルで1日営業する場合：

```bash
venv/bin/python -m cat_cafe_sim run --policy learned --model models/cat_q.json \
  --seed 42 --output reports/learned_day_seed42.json
python3 -m cat_cafe_sim replay reports/learned_day_seed42.json
```

`--config`省略時はモデル内の設定を使います。接客ルールがモデルと異なる設定は開始前に拒否します。
営業中の未知状態率も記録します。[営業への接続と比較結果](Docs/Phase2_LearnedCafePolicy.md)を参照してください。

接客環境では、消耗した猫・閉店間際からの開始状態も指定できます。

```python
from cat_cafe_sim.envs import CatInteractionEnv

env = CatInteractionEnv()
observation, info = env.reset(seed=42, options={
    "stamina": 20, "spirit": 31, "remaining_ticks": 5,
})
```

開始条件の制約・終了判定・ログ再生は[接客開始状態の指定](Docs/Phase2_InteractionStart.md)を参照してください。
開始条件を混ぜて再学習する場合は、別の設定を指定します。

```bash
venv/bin/python -m cat_cafe_sim.training train --training config/cat_training_mixed.json --seed 42
```

旧モデルとは別の`models/cat_q_mixed_seed42.json`へ保存します。
複数seedの再学習手順と営業比較は[開始条件の混合と比較結果](Docs/Phase2_MixedStartTraining.md)を参照してください。

混合開始モデルの不満退店を分析し、体力区間を細分化した候補も比較しました。
[失敗分析・再現手順・採用判断](Docs/Phase2_FailureAnalysis.md)を参照してください。

人対人の行動を人対猫に置き換える[行動原案](Docs/HumanToCatActionProposal.md)について、
[主体・行動効果・猫の反応・最小実装範囲の設計案](Docs/HumanToCatInteractionDesign.md)を整理しています。
単独交流の初期実装を追加しました。実行・再生・固定方策の比較ができます。

```bash
python3 -m cat_cafe_sim.human_cat_demo run --actions direct direct pause feint
python3 -m cat_cafe_sim.human_cat_demo replay reports/human_cat_session.json
python3 -m cat_cafe_sim.human_cat_demo compare
```

[実装範囲・操作方法・48条件の比較結果](Docs/HumanToCatInteractionImplementation.md)を参照してください。

ボタンで猫との交流を試す場合（Tkinterとデスクトップ環境が必要）：

```bash
python3 -m cat_cafe_sim.human_cat_gui
```

6つの行動、日本語の反応・履歴、関心・体力表示、条件変更・再開始、ログ保存に対応しています。
[試遊画面の操作方法と検証結果](Docs/HumanToCatPlaytestUI.md)を参照してください。

次の拡張として、[お客のテンション、心をつかむ／心を開く、同時発動の資金ボーナス、動作種類の追加](Docs/HumanToCatSpecialActions.md)を整理しています。特別行動は版2、8種類と個性は版3で実装済みです。

[特別行動の初回実装用仕様](Docs/HumanToCatSpecialActionsSpecification.md)には、ゲージ増減・予約処理・猫の任意発動・終了条件・暫定ボーナスとターン例をまとめています。

テンションと特別行動を含む版2も利用できます。試遊画面の既定は後述の版3です。CLIでは版を指定します。

```bash
python3 -m cat_cafe_sim.human_cat_gui
python3 -m cat_cafe_sim.human_cat_demo run --rules 2 --tension 80 --engagement 80 --actions connect
python3 -m cat_cafe_sim.human_cat_demo compare --rules 2
```

[版2の操作・互換性・比較結果](Docs/HumanToCatSpecialActionsImplementation.md)を参照してください。
初期版の試遊画面は`python3 -m cat_cafe_sim.human_cat_gui --rules 1`で起動できます。

次の拡張として、[8種類の交流・猫ごとの好みと強さの好み・飽き・切り替えの暫定仕様](Docs/HumanToCatInteractionTypes.md)をまとめています。

8種類の交流と5つの個性プリセットを追加しました。画面で変更先と次の猫の個性を選べます。

```bash
python3 -m cat_cafe_sim.human_cat_gui
python3 -m cat_cafe_sim.human_cat_demo run --rules 3 --preset '穏やかな甘えん坊' --actions switch:pet direct
python3 -m cat_cafe_sim.human_cat_demo compare --rules 3
```

[版3の操作・設定・120条件の比較結果](Docs/HumanToCatInteractionTypesImplementation.md)を参照してください。
旧版の試遊画面は`--rules 1`または`--rules 2`で選択できます。

個性別の成功経路と低体力条件を[到達経路の診断](Docs/HumanToCatReachabilityAnalysis.md)にまとめました。

```bash
python3 -m cat_cafe_sim.evaluation.reachability
python3 -m cat_cafe_sim.evaluation.reactive_adapt
```

探索は個性を知った診断用です。公開反応だけの方策とは分けて比較しています。
