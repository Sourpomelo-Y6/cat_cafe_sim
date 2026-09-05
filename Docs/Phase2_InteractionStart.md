# 接客開始時の体力・気力・残り時間の指定

更新日：2026-09-05

本書は開始状態APIの実装記録。続く[開始条件の混合と再学習](Phase2_MixedStartTraining.md)で
混合設定・複数seedの再学習・営業比較まで実装済み。

営業評価で多かった未知状態を学習できるよう、まず接客環境の開始条件を指定できるようにした。
今回の実装範囲は開始状態の指定、境界条件テスト、開始状態を含むログ再生。
開始条件のランダム生成、学習設定への組み込み、再学習・旧モデルとの成績比較は次の実装単位とする。

## 使用例

既存の`requirements-env.txt`以外の依存は追加していない。

```python
from cat_cafe_sim.envs import CatInteractionEnv
from cat_cafe_sim.replay import save

# 体力12.5・気力29・閉店まで3tickの新しい接客
# 資源上限や営業時間そのものは既存の設定から変更しない。
env = CatInteractionEnv()
observation, info = env.reset(seed=42, options={
    "stamina": 12.5,
    "spirit": 29,
    "remaining_ticks": 3,
    "preferences": (1, 1),
})
while True:
    observation, reward, terminated, truncated, info = env.step(6)
    if terminated or truncated:
        break

print(info["initial_state"], info["elapsed_steps"], info["accounting"])
save(env.core, "reports/late_start.json")
env.close()
```

この例は3回休んだ後に閉店し、着席3tick分の料金30を請求する。
開始以前の37tickに対する課金や気力消費は発生しない。

```bash
python3 -m cat_cafe_sim replay reports/late_start.json
venv/bin/python -m unittest discover -s tests -v
```

## resetの契約

`reset(seed=..., options=...)`で以下を受け付ける。

| 項目 | 指定できる値 | 省略時 |
|---|---|---|
| stamina | 0より大きく、設定上限以下の有限数 | max_stamina |
| spirit | 0以上、設定上限以下の有限数。0には下記の制限あり | max_spirit |
| remaining_ticks | 1〜opening_ticksの整数 | opening_ticks |
| preferences | 既存の2種類の非公開の好み | コンストラクターの設定 |

割合ではなく体力・気力の実数値を指定する。観測では従来どおり設定上限で正規化する。
残り時間から開始tickを`opening_ticks - remaining_ticks`として計算する。
最初のstep内でそのtickに客が来店・着席し、猫行動を1回処理する。
reset自体では時間、会計、気力回復、報酬イベントを進めない。

開始時点は「新しい客に対して猫が行動を選択できる時点」と定義する。
体力0は割り当て前の回復判定が必要な状態なので受け付けない。
回復をreset内で行って気力消費の報酬を失ったり、行動できない猫の待機列エピソードを作ったりしないための制約。

気力0は、既存設定`allow_zero_spirit_after_refill=True`の場合だけ許可する。
その場合も体力は正である必要があり、体力を使い切った後は既存の接客不能ルールに従う。
気力が回復コスト未満／同値でも、正の気力・体力があれば開始可能。
満足目標到達と体力0が同時なら、従来どおり成功を優先する。

満足・交流履歴・来店回数は新規客として初期化する。過去の接客途中の満足・飽きを復元するAPIではない。
指定値のNaN・Infinity・範囲外・不正型・未知のオプションは拒否し、
開始条件の検証に失敗した場合は既存の接客状態・時計・乱数を変更しない。
次のresetでオプションを省略すれば、前回の指定を持ち越さず既定値に戻る。

## 時計と終了

営業時計と環境内の経過step数を分ける。

- `observation["remaining_ticks"]`：実際に閉店まで残る時間。
- `info["elapsed_steps"]`：今回のreset後に実行したstep数。
- `info["initial_state"]`：実際に採用した体力・気力・残り時間。好みは含まない。
- `core.tick`および営業集計の`ticks`：営業開始を0とする時計。経過step数ではない。

`max_steps`は絶対的な営業tickではなく、今回の接客の経過step数に対して適用する。
例えば残り5tickから`max_steps=2`で開始した場合、2回の行動後・残り3tickで打ち切る。
外部打ち切りは会計なしの`truncated=True`で、学習用の次状態マスクを保持する。
同時に成功・不満・閉店が起きた場合は本来の終了を優先して`terminated=True`とする。

## coreとログ再生

`core.StartState(stamina, spirit, tick=0)`を追加した。
`SimulationCore(..., start_state=...)`で指定し、営業coreでも同じ開始状態の検証を行う。
省略時は従来どおりtick 0、体力・気力は最大値。

これは「過去の営業を途中から復元するスナップショット」ではない。
過去の客・売上・接客履歴は生成せず、設定内の開始tick以降の来客だけを処理する。
接客環境では来店予定を開始tickの1人だけに置き換える。

営業JSONには`start_state`として体力・気力・開始tickを保存する。
再生時に同じ状態から初期化するため、途中tickからの接客ログでも状態・イベント・会計を照合できる。
旧ログに`start_state`がなければ従来の開始状態を使う。
開始条件以外のゲームルールと既存モデルの観測仕様は変えていないため、
シミュレーター0.2.0・環境cat-interaction-v2・モデル形式は維持する。

## 検証結果と残りの作業

既存69件に14件を追加し、83件が成功。
開始状態・観測範囲、最初の着席、気力の回復境界、成功と閉店の優先順位、
開始からのstep上限、不正reset時の状態保持、既定値への復帰、NumPyスカラー入力、
同seed・同開始条件・同行動列の再現、開始条件を含むログと旧ログの再生を確認した。

既存の学習seed 42モデルを読み込み直し、保存されていた評価結果と45軌跡
（3方策×3種類の好み×5seed）が一致した。
旧営業ログと、新しい「体力12.5・気力29・残り3tick」のログも、外部ライブラリなしで再生一致した。

まだ学習コマンドは従来の満タン・営業時間最初の接客を使用する。
次は開始条件の組み合わせと混合比を設定化し、学習用・調整用・未使用評価用を分離して再学習する。
その後に固定方策・旧モデル・新モデルを同じ営業条件で比較し、未知状態率と営業指標を確認する。
今回の変更だけで旧モデルの成績が改善したとは扱わない。
