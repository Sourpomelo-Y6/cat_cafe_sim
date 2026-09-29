# 猫カフェシミュレーター

新規ゲームの派遣先に「山あいの宿への訪問」を追加しました。この派遣先だけで家出トラブルが起こり、捜索費を払って連れ戻すか、無料で帰還を待つか選べます。出発前に猫ごとの発生率を確認できます。[新派遣先と家出トラブルの仕様](Docs/HumanToCatDispatchTrouble.md)を参照してください。

新規ゲームの「準備・お店」→「ペットショップで迎える…」で、固定3匹の個性・特徴・特性・価格を比較して購入できます。飼育枠と支払い後の資金を確認し、購入費と加入履歴を記録します。[ペットショップの仕様](Docs/HumanToCatPetShop.md)を参照してください。

新規ゲームの商店街への派遣では、帰還後に猫を紹介されます。個性・特徴・特性・費用・飼育枠を確認し、迎える／見送るを選べます。[派遣先からの猫紹介](Docs/HumanToCatDispatchIntroduction.md)を参照してください。

保護猫の紹介元を12種類へ増やしました。初回3匹を維持し、以後は異なる個性・特徴・特性の猫を3匹ずつ順番に紹介します。候補一覧の特徴を比較して、お客さんの好みや派遣先に合う猫を選べます。[受け入れと候補の仕様](Docs/HumanToCatRecruitment.md)を参照してください。


新規ゲームの在籍猫上限は6匹です。「準備・お店」→「飼育スペースを拡張する…」で費用500を払い、9匹へ拡張できます。購入当日から日次維持費20が加わります。旧セーブは上限なしを維持します。[飼育スペースの仕様](Docs/HumanToCatHousing.md)を参照してください。


新規の人気目標ゲームでは、第2段階達成後に翌日の特別予約を受け入れるか選べます。長毛猫と「心を開く」の公開条件を満たすと追加料金200・人気＋5を得られ、見送りにはペナルティがありません。[特別予約の仕様](Docs/HumanToCatReservations.md)を参照してください。

人気目標の最終段階をクリアすると、翌営業日から三毛猫との特別な時間を望むVIP客が来店します。三毛猫、心をつかむ・心を開く、同時発動の複合条件を満たすと追加料金400・人気＋10を得られます。[VIP客の仕様](Docs/HumanToCatVipCustomer.md)を参照してください。

新規ゲームでは、来店停止を2回繰り返したお客さんに信頼回復イベントが発生します。費用を使わず今後の接客で回復を試みるか、対応しないかを選び、回復中の「不満」または未対応で永久離脱します。[信頼回復と永久離脱](Docs/HumanToCatCustomerTrust.md)を参照してください。

新規ゲームでは、接客終了時に親しみ・特別行動・関心とテンション・好みの一致・高難度条件・体力切れから「満足・普通・不満」を判定します。満足は料金・人気・常連度・不満回復、不満は累積不満へ反映し、営業ログ・閉店結果・顧客名簿で確認できます。[接客評価の仕様](Docs/HumanToCatCustomerSatisfaction.md)を参照してください。

新規ゲームでは、待機列満員・待機時間切れ・高難度条件未達でお客さんの累積不満が増えます。100に達すると翌日から7日間来店を停止し、その後は不満50で復帰します。良い接客では不満が下がり、現在値と復帰予定を顧客名簿で確認できます。[累積不満の仕様](Docs/HumanToCatCustomerDiscontent.md)を参照してください。

新規ゲームでは、親しみが増える接客で店への常連度が25上がり、100になると常連になります。通常客は本来来ない固定曜日に週1回追加来店し、常連度・追加曜日・今日／翌日の予定を顧客名簿で確認できます。[常連度の仕様](Docs/HumanToCatCustomerLoyalty.md)を参照してください。

人気目標第1段階の達成後は4席、第2段階の達成後は5席へ、それぞれ資金1,000で増設できます。席は購入当日から使用でき、各購入の翌日から通常のお客さんが1人ずつ増えます。[段階的な増設](Docs/HumanToCatExpansion.md)を参照してください。

新規ゲームでは、営業日と休業日の終了時に基本40＋1席あたり10の店舗運営費を支払います。増設画面で増設後の日次費用を確認でき、資金が0以下になるとゲームオーバーです。[店舗運営費の仕様](Docs/HumanToCatOperatingCosts.md)を参照してください。

閉店結果と複数日の比較画面では、開始資金、収入、支出、純収支、終了資金を確認できます。比較画面には表示期間の累計も表示します。[日次収支の仕様](Docs/HumanToCatDailyFinance.md)を参照してください。

人気目標第1段階の達成後、費用800で待合スペースを強化できます。待機上限が4人から5人、待機猶予が8tickから10tickになり、日次運営費が10増えます。[待合スペースの仕様](Docs/HumanToCatWaitingArea.md)を参照してください。

新規ゲームでは、地域のお祭り・雨・支援物資・設備トラブル・保護団体からの支援依頼の店舗イベントが日ごとに発生します。設備トラブルでは修理、1席を止める応急処置、休業から対応を選べます。支援依頼では資金と人気の配分を選べます。[店舗イベントの仕様](Docs/HumanToCatStoreEvents.md)を参照してください。

新規の「人気3段階」では、第1段階達成で白猫好きのこだわり客が解放されます。翌日から来店し、白猫を担当にして「心をつかむ」を1回以上発動すると追加料金100を得られます。条件と直近の結果は顧客名簿で確認できます。[高難度客の初回仕様](Docs/HumanToCatAdvancedCustomers.md)を参照してください。

各目標のクリア成果を共通画面で確認できるようになりました。「結果・記録」→「クリア記録…」から、達成時の資金・人気・在籍猫数・累計接客売上を見返せます。[クリア結果の仕様](Docs/HumanToCatClearResults.md)を参照してください。

新規ゲーム開始時に「人気3段階」「有力者の満足度」「猫6匹との好感度」「自由営業」を選べます。[目標選択の仕様](Docs/HumanToCatObjectiveSelection.md)を参照してください。

猫の詳細に「できごと」タブを追加しました。加入・派遣・帰還・譲渡・ケアなどを猫別に確認でき、選んだ行の全文を下欄で読めます。[猫の詳細と履歴](Docs/HumanToCatCatDetailsPlan.md)を参照してください。

人気目標を3段階（150 → 225 → 300）に拡張しました。各段階10日間で、達成後に次へ挑戦するか自由営業を選べます。既存セーブの単段階目標は維持します。[人気目標の仕様](Docs/HumanToCatPopularityGoal.md)を参照してください。

近所のお店への新しい派遣でケア用品を入手し、「準備・お店」→「所持品・ケア…」から在店猫のストレスを下げられます。[アイテム報酬と使用の仕様](Docs/HumanToCatItems.md)を参照してください。

新規ゲームでは4日目の準備時に保護猫の受け入れ依頼が届きます。案内欄から猫と費用を確認し、迎える／見送るを選べます。[受け入れ依頼の仕様](Docs/HumanToCatIntakeRequest.md)を参照してください。

商店街・郊外への新しい派遣では、1日目終了時に選択イベントが発生します。案内欄の「確認する」から回答でき、報酬・疲労・ストレスが変化します。[派遣中イベントの仕様](Docs/HumanToCatDispatchEncounters.md)を参照してください。

「準備・お店」→「席の接客設備を整える…」で、おもちゃセットとくつろぎクッションを各300で購入できます。席ごとに1つ設置でき、購入済み設備の移動・取り外しは無料です。[接客設備の仕様](Docs/HumanToCatSeatEquipment.md)を参照してください。

新規ゲームは1日目を月曜日とし、お客さんごとに来店曜日が変わります。名簿で今日・翌日の予定を切り替えて確認できます。休業でも曜日は進み、旧セーブは従来の予定を維持します。[曜日別来店の仕様](Docs/HumanToCatWeekdays.md)を参照してください。

「準備・お店」→「お客さんの名簿・来店予定…」で、その日の来店予定・好み・来店回数・猫別の親しみを確認できます。担当割り当てにもお客さんの表示名を使います。[名簿と来店予定の仕様](Docs/HumanToCatCustomers.md)を参照してください。

「結果・記録」→「猫との好感度目標・結果…」で、プレイヤーへの好感度80以上の在籍猫6匹を目指す任意目標を開始できます。派遣中・家出中も含み、譲渡済みは対象外。期限なしで、達成後も営業を続けられます。[好感度目標の仕様](Docs/HumanToCatBondGoal.md)を参照してください。

通常営業の画面を「営業」「準備・お店」「結果・記録」に整理しました。営業ログは常時表示し、確認待ちのイベントは案内欄から直接開けます。[画面構成と操作](Docs/HumanToCatUIFlow.md)を参照してください。

新規の初期猫と新しい保護猫候補に、長所・短所を持つ「接客好き」「のんびり屋」「外出好き」の特性を追加しました。猫の詳細・候補で効果を確認でき、接客の疲労・ストレス、休養回復、派遣報酬・帰還ストレスへ反映します。既存セーブの猫には自動付与しません。[特性の初回仕様](Docs/HumanToCatTraits.md)を参照してください。

新規ゲームでは「10日以内に人気150」の目標に挑戦します。好感度につながる反応が得られた接客から閉店時に人気を獲得し、家出による減少後に判定します。「結果・記録」→「人気目標・結果…」で達成・未達を確認した後も営業を続けられます。旧セーブでは準備中に任意で開始できます。[人気目標の仕様](Docs/HumanToCatPopularityGoal.md)を参照してください。

`python3 -m cat_cafe_sim.cafe_interaction gui` で「新しく始める」「セーブから続ける」の開始画面を開きます。新規ゲームは猫5匹・2席・資金1,000・人気100、経営ルール有効で開始します。ゲームごとに保存先を分け、終了後は「結果・再開始…」から別の店を始められます。[開始・再開の仕様](Docs/HumanToCatNewGame.md)を参照してください。

準備中の「準備・お店」→「保護猫を迎える…」で、個性の異なる3匹を確認して迎えられます。初期費用は各200で、支払い後に資金が残る場合だけ実行できます。加入時は休養予定です。[受け入れの初回仕様](Docs/HumanToCatRecruitment.md)を参照してください。

経営ルール未導入の旧セーブ・試遊では、「結果・記録」→「家出・帰還・経営状態…」から有効にできます。開始時だけ所持金を最低1,000まで補充し、以降は資金0以下・人気0で終了します。[経営ルールの初回仕様](Docs/HumanToCatManagement.md)を参照してください。

「結果・記録」→「譲渡の申し出・設定…」で、保護猫の譲渡イベントをONにできます（初期OFF）。お客への親しみが80以上でプレイヤーへの好感度を上回ると申し出が発生し、譲渡するか見送るか選びます。[譲渡の仕様](Docs/HumanToCatAdoption.md)を参照してください。

準備中は「猫の詳細…」から、プレイヤーがコマンドを選ぶ交流を始められます。店全体で1日3セット、1セット最大10ターン。休養予定の猫も対象で、接客と同じ行動・反応を試せます。好感度・体力・使用セット数・途中状態を営業セーブへ保存します。[プレイヤー交流の仕様](Docs/HumanToCatPlayerInteraction.md)を参照してください。

通常営業の「準備・お店」→「派遣・帰還を確認する…」から、余った猫を近所のお店へ派遣できます。閉店・休業で期間が進み、帰還結果を確認すると報酬を受け取れます。[派遣・帰還の仕様](Docs/HumanToCatCafeActivities.md)を参照してください。

通常営業の猫一覧で猫を選び「猫の詳細…」を押すと、状態・個性、お客別の親しみ、日次実績を確認できます。閲覧中は営業が一時停止し、閉じた後も停止を維持します。

[猫の加入方法の案](Docs/HumanToCatRecruitmentPlan.md)に、受け入れ・購入・イベント加入などを整理しています。スカウトは実装負担を考慮して低優先度とします。

[実装予定の機能案](Docs/HumanToCatPlannedFeatures.md)に、猫の派遣・情報と履歴・譲渡・プレイヤー交流・家出・イベント・特性と、3つのクリア案を記録しています。

現在はゲーム全体の流れを固めることを優先し、回復量などの細かなバランス調整は後回しにします。[開発方針](Docs/CatCafeSimulation_ImplementationGuide.md)を参照してください。
[ゲーム全体の流れと実装順](Docs/HumanToCatGameFlowPlan.md)に、現行の遊び方・不足する経営要素・未決定事項と、次の実装順の提案を整理しています。派遣・イベント・終了判定を含む一日の流れへ更新し、[猫の詳細画面](Docs/HumanToCatCatDetailsPlan.md)に加え、派遣3種類と帰還確認の初回実装まで進めています。

新規ゲームでは、接客・休養・派遣で猫が経験を得ます。合計20になると接客・休養・派遣から得意分野を1つ選び、体力回復、疲労回復、派遣報酬の効果を得られます。接客得意の猫は、親しみが増えた接客を15行動分経験すると、遊び・触れ合い・静かな交流から得意な分類を選び、その分類の関心増加が1.1倍になります。進捗と効果は、猫の詳細、営業の猫一覧、出勤・休養、派遣画面で確認できます。[猫の経験・得意行動の成長](Docs/HumanToCatCatGrowthPlan.md)を参照してください。

営業前の「今日は休業する」で、来客なしに在店猫を1日休ませて翌日へ進めます。出勤予定がある場合も利用できます。[休業日の仕様](Docs/HumanToCatCafeDayOffPlan.md)を参照してください。

全猫出勤・交代休養・疲労による休業を比較する[100日営業の検証](Docs/HumanToCatLongTermEvaluation.md)に、測定条件・結果と今後の調整案をまとめています。
続く[疲労を優先した休養・割り当ての比較](Docs/HumanToCatFatiguePriorityEvaluation.md)では、疲労順に1匹／2匹を休ませる方針と、負担の低い猫から割り当てる方針を検証しています。

営業セーブを軽量な形式2に変更しました。旧セーブも読み込めます。別名での変換方法と詳細ログの扱いは[営業セーブの軽量化](Docs/HumanToCatCompactSaves.md)を参照してください。

疲労が高い猫は閉店時に発症することがあります。療養中は接客できず、必要な日数を休むと復帰できます。[病気と療養・復帰](Docs/HumanToCatCafeHealth.md)を参照してください。

営業前の「準備・お店」の「出勤・休養を決める…」で担当可能な猫を設定できます。「疲労が高い2匹を休養する案を作成」で予定を提案し、確認・手動変更してから保存できます。全員休養の場合は「今日は休業する」へ案内します。前日の接客量を基準にした出勤時の予測疲労・発症確率と、休養時の予測を比較できます。接客で増える疲労と休養日の回復を記録し、翌日の体力全回復は維持します。[出勤・休養と長期疲労](Docs/HumanToCatCafeShifts.md)を参照してください。

「営業結果を比較…」では日別の売上と猫別の接客回数・消耗・親しみ増減を一覧で比較できます。

通常営業画面では「閉店結果・翌日へ」で売上・猫の消耗・親しみの変化を確認し、所持金と親しみを引き継いで翌日へ進めます。詳しくは[閉店結果と翌日の営業](Docs/HumanToCatCafeDays.md)を参照してください。

交流の目的・終了・成果を見直した経緯は[交流の目的・終了・成果の見直し](Docs/HumanToCatInteractionPurpose.md)を参照してください。
単独交流の現行版4では、猫からお客への親しみを組み合わせごとに保存します。任意終了・時間終了・体力切れと、親しみ・資金・消耗の成果を分けました。
[版4の操作・保存・検証結果](Docs/HumanToCatRelationshipImplementation.md)を参照してください。低体力から特別行動を達成することは必須要件にしません。
[親しみ・成果確定・再会の初回仕様](Docs/HumanToCatRelationshipSpecification.md)に、暫定の増減量と保存・結果表示の扱いを具体化しています。


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
「自動割り当て」を選べば、待機順の案内も自動化できます。営業は複数猫・初期2席、増設後は最大5席の同時交流に対応しています。
コマンドを手動で選ぶ検証画面は`python3 -m cat_cafe_sim.cafe_interaction gui --manual`で開きます。
CLIの`run`も操作列を省略すると閉店まで自動進行します。[操作と自動選択の規則](Docs/HumanToCatAutomaticCafe.md)を参照してください。

登録済みの猫から担当を選び、猫ごとの体力・個性・お客への親しみを確認できます。自動割り当ては体力に余裕がある猫を優先します。
[参加猫の指定・担当交代・個別の体力管理](Docs/HumanToCatCafeRoster.md)を参照してください。

通常営業は初期2席、増設後は最大5席で同時に交流します。席ごとの状態と会計を確認できます。
テスト用の猫5匹は`python3 -m cat_cafe_sim.cafe_interaction seed-playtest`で追加できます。
[2席営業の操作・テスト用の猫](Docs/HumanToCatMultiSeatCafe.md)を参照してください。

「営業を保存…」「続きから開く…」で、同じ営業日の途中から再開できます。読み込み後は一時停止状態になります。
起動時に開く場合は`python3 -m cat_cafe_sim.cafe_interaction gui --resume saves/cafe_day.json`を使います。
[営業セーブの操作・整合性・制限](Docs/HumanToCatCafeSaves.md)を参照してください。

[お客さんの特性・猫の特徴と相性の案](Docs/HumanToCatCustomerPreferencesPlan.md)に、特徴と特性の区分や複数保持を整理しています。[初回仕様](Docs/HumanToCatCustomerPreferences.md)として、新規ゲームの猫の特徴とお客さんの好み、一致時のテンション上昇1.25倍、配置前の相性比較を実装済みです。

「結果・記録」→「有力者目標・結果…」から、[有力者への派遣と満足度目標](Docs/HumanToCatPatronGoal.md)を開始できます。2日の派遣帰還で満足度＋25、100でクリア。人気目標とは独立し、結果確認後も営業を続けられます。

準備中の「準備・お店」→「席を増やす…」から、2席を3席、人気目標の進行後は4席・5席へ増設できます。[増設仕様](Docs/HumanToCatExpansion.md)を参照してください。支払い後に資金が残る場合だけ購入でき、増設後の席数を派遣条件と保存再開にも反映します。

「準備・お店」→「休養スペースを購入する…」から[休養スペース](Docs/HumanToCatRestEquipment.md)を購入できます。暫定400で、在店休養時の疲労回復＋10（特性補正後に加算）。休養予測・支出履歴・保存再開に対応しています。
