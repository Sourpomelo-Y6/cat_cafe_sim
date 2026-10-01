# 猫カフェシミュレーター

猫の出勤・休養・派遣を計画し、自動接客の成果で店を発展させるシミュレーターです。新規ゲームでは人気3段階、有力者の満足度、猫6匹との好感度、自由営業から目標を選べます。

## 起動と資料

通常のゲームを起動するには、プロジェクトのルートで次を実行してください。Python 3.12で動作確認しています。

```bash
python3 -m cat_cafe_sim.cafe_interaction gui
```

開始画面で新規ゲームかセーブ再開を選びます。通常営業では猫と席の割り当てを判断し、交流コマンドは自動で進みます。

| 知りたいこと | 資料 |
| --- | --- |
| 資料全体から探す | [ドキュメント索引](Docs/README.md) |
| 現在遊べる機能と一日の流れ | [全体計画](Docs/HumanToCatGameFlowPlan.md)、[画面構成](Docs/HumanToCatUIFlow.md) |
| 開発を引き継ぐ | [引き継ぎ資料](Docs/DevelopmentHandoff.md) |
| 今後の機能候補 | [実装予定](Docs/HumanToCatPlannedFeatures.md) |
| 保存形式と旧セーブの扱い | [営業セーブ](Docs/HumanToCatCafeSaves.md)、[軽量形式](Docs/HumanToCatCompactSaves.md) |
| 追加機能の経緯 | [整理前の資料](Docs/History/README.md) |

## 現在のゲーム機能

| 分野 | 実装済みの内容 |
| --- | --- |
| 猫と活動 | 詳細・できごと履歴、出勤・休養・療養、プレイヤー交流、活動経験と得意分野・最大3つの交流分類と最初の分類で最大2行動・2つ目の分類で最大2行動・3つ目の分類で最大2行動の個別熟練 |
| 加入と飼育 | 保護猫候補、受け入れ依頼、ペットショップ購入、商店街・撮影スタジオ・常連からの紹介、6→9→12匹への飼育枠拡張 |
| 施設と経営 | 2〜8席への増設、休養・待合・5種類の接客設備、3種類のケア用品、運営費と日次・期間収支 |
| お客さん | 曜日別来店、特徴との相性、満足評価、常連・累積不満・信頼回復、白猫好き・曜日を分けた静かな交流客・遊び客・日曜の触れ合い客・予約・VIP客 |
| 派遣とイベント | 段階解放、歓迎条件と報酬、撮影スタジオなど派遣先専用の選択イベント、店舗イベント、山あいの宿だけの家出トラブル |
| 目標と保存 | 3種類のクリア目標と自由営業、共通クリア記録、資金・人気のゲームオーバー、途中保存と詳細リプレイ |

機能ごとの条件・暫定数値・互換方針は[ドキュメント索引](Docs/README.md)から各仕様を参照してください。旧セーブへの適用は機能ごとに異なり、新規機能を一括で後付けするものではありません。

## 開発用CLIと検証

以下の1日営業CLI・学習環境は、通常ゲームとは別の検証用入口です。既存の実行例を残しています。

1日営業CLIとPhase 2の接客環境も利用できます。
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

テンションと特別行動を含む版2も利用できます。試遊画面の既定は版4です。CLIでは版を指定します。

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
python3 -m cat_cafe_sim.human_cat_gui --rules 3
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

### 親しみ・任意終了・再会（版4）

```bash
python3 -m cat_cafe_sim.human_cat_gui
python3 -m cat_cafe_sim.human_cat_demo run --rules 4 --cat-id cat-1 --customer-id guest-1 --actions direct finish --relationships saves/example.json --save-result --output reports/relationship_example.json
python3 -m cat_cafe_sim.human_cat_demo compare --rules 4
```

画面では「切り上げる」で成果を確定し、同じ猫ID・客IDで再会すると親しみを引き継ぎます。
保存先の既定は`saves/relationships.json`です。CLIは`--save-result`指定時だけ関係データを更新します。
ログ再生は関係データを更新しません。営業の所持金・体力との接続は後述の営業試遊で扱い、客満足との接続は今後の作業です。

親しみと個性に応じた[再会時の描写と関係の目安](Docs/HumanToCatRelationshipPresentation.md)も表示します。
結果画面では、親しみの数値に加えて段階の変化を確認できます。

「関係一覧から再会…」で保存済みの相手と直近の親しみの増減を確認し、その相手と再会できます。
[関係一覧の操作とデータの扱い](Docs/HumanToCatRelationshipList.md)を参照してください。

[猫の名前と個性を登録](Docs/HumanToCatCatProfiles.md)すると、同じ猫IDの再会には保存済みの個性を使います。関係一覧には名前も表示します。

試遊画面は「交流の様子」と「猫の登録・次の交流」のタブに分かれています。
猫の登録・関係一覧・個性・動作の変更先は設定側のタブで選べます。タブ内は縦スクロールでき、行動ボタンとログ欄は常に表示されます。

### 営業中の交流

来店したお客を選び、版4の交流から時間料金・特別行動の資金・残り体力・親しみを営業へ反映する試遊を追加しました。

```bash
python3 -m cat_cafe_sim.cafe_interaction gui
python3 -m cat_cafe_sim.cafe_interaction run --operations wait start:guest-1 direct finish
python3 -m cat_cafe_sim.cafe_interaction replay reports/cafe_interaction.json
```

[営業との接続仕様・操作方法](Docs/HumanToCatCafeIntegration.md)を参照してください。
親しみと猫の登録に加え、営業の所持金・時計・体力・交流途中の状態も営業セーブで保存・再開できます。

通常の営業画面では、プレイヤーは担当猫を割り当て、その後の交流は自動で進みます。
「自動割り当て」を選べば、待機順の案内も自動化できます。営業は複数猫・初期2席、増設後は最大8席の同時交流に対応しています。
コマンドを手動で選ぶ検証画面は`python3 -m cat_cafe_sim.cafe_interaction gui --manual`で開きます。
CLIの`run`も操作列を省略すると閉店まで自動進行します。[操作と自動選択の規則](Docs/HumanToCatAutomaticCafe.md)を参照してください。

登録済みの猫から担当を選び、猫ごとの体力・個性・お客への親しみを確認できます。自動割り当ては体力に余裕がある猫を優先します。
[参加猫の指定・担当交代・個別の体力管理](Docs/HumanToCatCafeRoster.md)を参照してください。

通常営業は初期2席、増設後は最大8席で同時に交流します。席ごとの状態と会計を確認できます。
テスト用の猫5匹は`python3 -m cat_cafe_sim.cafe_interaction seed-playtest`で追加できます。
[2席営業の操作・テスト用の猫](Docs/HumanToCatMultiSeatCafe.md)を参照してください。

「営業を保存…」「続きから開く…」で、同じ営業日の途中から再開できます。読み込み後は一時停止状態になります。
起動時に開く場合は`python3 -m cat_cafe_sim.cafe_interaction gui --resume saves/cafe_day.json`を使います。
[営業セーブの操作・整合性・制限](Docs/HumanToCatCafeSaves.md)を参照してください。

[お客さんの特性・猫の特徴と相性の案](Docs/HumanToCatCustomerPreferencesPlan.md)に、特徴と特性の区分や複数保持を整理しています。[初回仕様](Docs/HumanToCatCustomerPreferences.md)として、新規ゲームの猫の特徴とお客さんの好み、一致時のテンション上昇1.25倍、配置前の相性比較を実装済みです。

「結果・記録」→「有力者目標・結果…」から、[有力者への派遣と満足度目標](Docs/HumanToCatPatronGoal.md)を開始できます。2日の派遣帰還で満足度＋25、100でクリア。人気目標とは独立し、結果確認後も営業を続けられます。

準備中の「準備・お店」→「席を増やす…」から、2席を3席、人気目標の進行後は4席・5席、最終段階達成後は6席、その購入後は7席・8席へ増設できます。[増設仕様](Docs/HumanToCatExpansion.md)を参照してください。支払い後に資金が残る場合だけ購入でき、増設後の席数を派遣条件と保存再開にも反映します。

「準備・お店」→「休養スペースを購入する…」から[休養スペース](Docs/HumanToCatRestEquipment.md)を購入できます。暫定400で、在店休養時の疲労回復＋10（特性補正後に加算）。人気第1段階達成後は、準備中に費用800で一度だけ強化し、設備の追加回復を合計＋20にできます。休養予測・購入と強化の支出履歴・保存再開に対応しています。

自由営業・好感度・有力者モードでは、営業準備中の「結果・記録」→「人気3段階へ挑戦…」から店の状態を引き継いで挑戦を開始できます。[途中開始の仕様](Docs/HumanToCatPopularityChallenge.md)を参照してください。

新規ゲームでは、最初に常連になったお客さんから翌日の準備中に猫紹介が届きます。「準備・お店」→「常連からの猫紹介…」で固定1匹のマロンを費用200で迎えるか見送るか選べます。[仕様](Docs/HumanToCatRegularIntroduction.md)。常連・派遣先の紹介と固定日の受け入れ依頼は、回答画面から飼育スペースを拡張して空き枠を確保できます。

新しく提示する保護猫候補のソラとフクには、[体力自慢](Docs/HumanToCatTraits.md)の特性があります。接客による疲労増加と在店休養による疲労回復がともに通常の0.75倍になります。提示済み候補や既存の猫の特性は維持します。

新規ゲームでは、体力自慢の猫を[猫の運動教室](Docs/HumanToCatExerciseDispatch.md)へ派遣できます。人気120以上・派遣報酬1回受取で解放し、疲労40以下で参加、2日後の帰還で基本報酬300を受け取ります。これから出発する派遣では1日目終了時に追加プログラムへの参加を選べ、参加なら帰還報酬＋80・疲労＋10になります。

「準備・お店」→「所持品・ケア…」で[栄養おやつ](Docs/HumanToCatItems.md)を1個150で購入し、在店猫の疲労を15回復できます。使用前に回復量を確認でき、特性による倍率は掛けません。疲労0なら消費せず、病気を治す効果もありません。

準備中の「所持品・ケア…」から、未使用のケア用品を50、栄養おやつを75、特製ケアセットを100で1個ずつ[売却](Docs/HumanToCatItems.md)できます。売却額の確認、履歴と日次収支に対応しています。

人気第1段階達成の翌日から「準備・お店」→「店先に通う猫…」でココと交流できます。1日1回、3回交流すると費用200で迎えられます。交流・加入は任意で、見送った日の進捗も維持します。迎える前は所属数・飼育枠・好感度目標に含めません。[店先の猫の仕様](Docs/HumanToCatVisitingCat.md)を参照してください。旧セーブへの後付けはありません。

購入済みの[待合スペース](Docs/HumanToCatWaitingArea.md)は、人気第2段階達成後の準備中に費用1,200で一度だけ2段階目へ強化できます。待機上限5→6人、猶予10→12tick、待合の維持費は日次10→20となり、当日から適用します。

新規ゲームでは、のんびり屋の猫を[静かな読書サロン](Docs/HumanToCatReadingDispatch.md)へ派遣できます。人気120以上・派遣報酬1回受取で解放、疲労40以下、2日・基本報酬300。1日目の専用イベントで延長に参加すると帰還報酬＋80・ストレス＋10になります。

準備中の「所持品・ケア…」で[特製ケアセット](Docs/HumanToCatItems.md)を1個200で購入し、在店猫の疲労とストレスを各10回復できます。両方0なら消費せず、片方だけが残っていても使えます。回復量は固定で、病気や療養日数は変えません。旧セーブも新しい購入から利用できます。

初回拡張済みの[飼育スペース](Docs/HumanToCatHousing.md)を、準備中に追加費用1,000で9匹から12匹へ拡張できます。飼育維持費は当日から合計40。人気条件はなく、紹介への回答待ちでも購入して受け入れを再判定できます。飼育ルールを持つ旧セーブは明示購入から対応し、上限なしの旧セーブを維持します。

新規ゲームでは接客好きの猫を[猫の撮影スタジオ](Docs/HumanToCatPhotoDispatch.md)へ派遣できます。人気120以上・派遣報酬1回受取で解放、疲労40以下、2日・基本報酬350。1日目に追加撮影を続ける（報酬＋100・疲労とストレス各＋15）／断って切り上げる（疲労とストレス各＋5）を選べます。

新規ゲームでは撮影スタジオへの最初の対象派遣から、帰還報酬の受領後にルカを紹介されます。穏やかな甘えん坊・白毛／短毛・接客好き、受け入れ費用250。迎える／見送るを選び、見送っても再紹介しません。回答画面から飼育スペースを拡張できます。[紹介仕様](Docs/HumanToCatDispatchIntroduction.md)を参照してください。

撮影スタジオは新規ゲームで白毛と得意分野「接客」を歓迎し、条件1件につき報酬＋20、両方一致なら＋40。出発前に一致と報酬見込み、帰還後に内訳を確認できます。保存済みの旧派遣条件・出発済み報酬は維持します。

派遣画面で猫を選び「派遣先を比較…」を開くと、行き先ごとの参加可否・日数・歓迎込み報酬・選択時の負担を比べられます。参加可能な行き先から既存の出発確認へ進めます。[比較仕様](Docs/HumanToCatDispatchComparison.md)を参照してください。

保護猫の候補一覧では受け入れ済みを標準で非表示にします。「受け入れ済みも表示」で、加入日付きの履歴を灰色で末尾に表示できます。候補や加入記録は保存したままです。

派遣先比較では「参加可能な派遣先だけ表示」と報酬見込みが高い順・期間が短い順を切り替えられます。行き先がないときは絞り込みを解除して参加不可の理由を確認できます。

保護猫の候補は特性・毛色・毛の長さで絞り込めます。「受け入れ済みも表示」と併用でき、該当なしの場合は「条件解除」で一覧へ戻せます。

所持品・ケア画面では「選んだ用品を使える猫だけ表示」で対象を絞り込めます。対象がいない場合は理由と表示解除を案内し、使用確認には猫・用品・回復前後の値を表示します。

新特性「働き者」は接客疲労0.75倍・接客ストレス1.25倍で、休養回復は通常どおりです。保護猫の5回目の紹介にナギ（働き者）・ミント・レオを追加し、15候補を5回で巡回します。既存の猫と提示済み候補は維持します。[特性仕様](Docs/HumanToCatTraits.md)を参照してください。

新規ゲームに働き者向けの[猫用品の体験会](Docs/HumanToCatProductTrialDispatch.md)を追加しました。疲労40以下・2日・基本報酬300、人気120以上と派遣報酬1回受取で解放。1日目に追加体験（報酬＋100・疲労とストレス各＋10）／通常終了を選べます。専用イベントはこの派遣先だけに適用し、旧セーブの派遣設定を維持します。
