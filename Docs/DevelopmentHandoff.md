# 開発引き継ぎ

更新日：2026-10-02。人気第1段階達成後に通常客4人を毎営業日に追加し、営業中に来店を分散する処理を実装しました。今回の基準コミットは `168b366`（お客さんの名前統一）です。今回の評価内容と検証結果は以下に記載しています。

現行機能と一日の流れは[全体計画](HumanToCatGameFlowPlan.md)、詳細仕様は[資料索引](README.md)、未着手候補は[実装予定](HumanToCatPlannedFeatures.md)を参照してください。過去の変更説明・コミット一覧・検証経緯は[整理前の引き継ぎ](History/2026-10-01/DevelopmentHandoff.md)と[履歴索引](History/README.md)へ保存しました。履歴内の「未コミット」「次の作業」は現在の指示ではありません。

## 次の検討事項

今回の依頼は、第1段階達成後の通常客増加です。新規開始時に人数を固定し、達成翌日以降に追加します。既存の曜日・増設客・高難度客の予定と、人数設定のない旧セーブは維持します。席上限8、目標・期限・料金・自動プレイの判断方針は変更しません。[仕様と自動プレイ比較](HumanToCatPopularCustomerGrowth.md)を参照してください。

ユーザーは人気目標・期限を現在の設定で維持する方針です。追加シードで第2段階の期限を再評価する提案には着手せず、代わりに自動プレイの判断をGUIで確認しやすくする改善を依頼しました。判断一覧は出勤・休養・購入・予約の実際の判断根拠を表示します。ゲームの数値・判断方針・保存形式は変更していません。詳細は[おまかせ画面の仕様](HumanToCatAutoPlayPlan.md#gui10日間おまかせ)を参照してください。

ユーザーはテスト用自動プレイの導入、実行内容が見える日本語ログ、将来のGUIで約10日まとめて進める機能、バランス調整を希望しています。[自動プレイ計画](HumanToCatAutoPlayPlan.md)に会話と設計案を整理しています。CLIの2方針とGUIの最大10日進行・日本語ログは実装済みで、同じ通常設定・シード0で5条件の予備評価まで完了しました。人気目標・期限・上限の調整は実装済みで、その他の数値調整と対象拡張は後続です。

初版は人気3段階の進行と正常終了・停止理由・保存再開の一致を確認します。GUIは共通の判断処理を使い、各段階の達成で停止します。[バランス予備評価](HumanToCatAutoPlayBalanceEvaluation.md)では通常クリア16日、増設なし14日でした。その後、クリアまでが短いという相談に沿って、[必要人気と期限を増やす比較](HumanToCatPopularityDurationEvaluation.md)を追加しました。ユーザーは長めの案（人気250→450→650、期限20→20→25日、上限650）の採用を決定しました。通常の新規ゲームへの反映まで実装しました。新しい他モードからの途中挑戦も長めの設定を使い、旧上限300の集計のみのゲームは従来の挑戦を使います。保存済みの目標・期限・上限は変更しません。休養設備には負担軽減の効果が見られました。人気目標・期限の採用決定は上記のとおりです。料金変更は未採用で、手動プレイ時間と追加シードの評価は後続です。直前の「派遣比較に帰還後の疲労・ストレス予測を追加」は未着手で、いったん置く案を提示しています。

基礎営業（`basic`）を既定のまま維持し、予測・投資・予約を使うクリア方針（`clear`）を追加しました。通常客増加前の設定では人気3段階を39日目に達成し、基礎営業は20日目に人気230で期限切れとなることを確認しています。自動プレイCLI・評価CLIの既定上限は60日、GUIのおまかせは最大10日のままです。再開時も `clear` を指定して利用します。GUIでも方針を選べます。今後は両方針の結果を使うバランス調整や対象拡張を検討します。[詳細方針](HumanToCatAutoPlayPlan.md#基礎営業とクリアを目指すモード)を参照してください。

## 開発方針と保留事項

- 実装・必要なテスト・関連資料の更新まで行い、コミットは別途依頼を受けて行う。
- 席数は当面8席まで。スカウトは低優先度で、加入や6匹クリアの必須経路にしない。
- 通常接客のコマンドは自動。プレイヤー交流とテスト用自動プレイは別の機能。
- 子猫は所属個体として管理せず、外部への引き渡し費用のみ扱う。お詫び費用は採用しない。
- 細かな数値調整は従来後回しだったが、ユーザーは自動プレイと併せたバランス調整を希望している。難易度・調整範囲は未確定。
- ストレスによる休養提案、猫ごとの日次貢献まとめ、通い猫の拡充、現行GUIでの猫の名前変更は保留。自動プレイの相談だけで採用済みと扱わない。

## 直近の完了内容

| コミット | 内容 | 詳細 |
| --- | --- | --- |
| 今回の変更 | 第1段階後の通常客4人増加・分散来店、旧セーブ互換、自動プレイ比較 | [通常客増加](HumanToCatPopularCustomerGrowth.md) |
| `168b366` | お客さんの固定名・客層の分離、旧セーブの表示互換 | [名簿](HumanToCatCustomers.md) |
| `adad42f` | おまかせ画面の判断一覧・理由全文・実行結果、操作ログとの切替 | [人気目標・期限の評価](HumanToCatPopularityDurationEvaluation.md) |
| `8d77eaa` | 長めの人気目標を新規ゲームへ反映、旧セーブと途中挑戦の互換性、CLI既定上限60日 | [人気目標](HumanToCatPopularityGoal.md) |
| `73d8165` | 必要人気・期限の比較、長めの案の採用決定 | [比較評価](HumanToCatPopularityDurationEvaluation.md) |
| `d74b3c0` | 自動プレイ5条件のバランス予備評価・集計CLI・テスト3件。ゲーム数値は変更なし | [予備評価](HumanToCatAutoPlayBalanceEvaluation.md) |
| `08f01e9` | GUI「10日間おまかせ」、方針選択・安全な中止・段階達成停止 | [計画](HumanToCatAutoPlayPlan.md) |
| `661fcf1` | 予測・投資・予約を使うクリア方針 | [計画](HumanToCatAutoPlayPlan.md) |
| `2d4127c` | 自動プレイ・日本語ログ・将来のGUI連携・バランス調整の希望を資料化（未実装） | [計画](HumanToCatAutoPlayPlan.md) |
| `5df1efe` | 美術館の長毛・派遣得意の歓迎条件、各報酬＋20 | [美術館](HumanToCatMuseumDispatch.md) |
| `184a5bf` | 美術館のブラッシングセット報酬、ストレス20回復・売却100 | [用品](HumanToCatItems.md) |
| `b52dd5d` | 人気第2段階で解放するマイペース向け美術館と交流依頼 | [美術館](HumanToCatMuseumDispatch.md) |
| `e502973` | マイペースと6回目の紹介、18候補・6回巡回 | [特性](HumanToCatTraits.md)、[紹介](HumanToCatRecruitment.md) |
| `6607d97` | 体験会の奇数日出発に撮影依頼、偶数日に追加体験 | [体験会](HumanToCatProductTrialDispatch.md) |
| `fb82418` | 人気第2段階達成後の休養スペース防音改修 | [休養設備](HumanToCatRestEquipment.md) |

## 実装の調査先

以下は `cat_cafe_sim/` からの相対パスです。テストはリポジトリ直下の `tests/` にあります。

| 対象 | 主な実装 |
| --- | --- |
| テスト用自動プレイ | `cafe_autoplay.py`（`AutoPlayer.step()`・CLI・段階達成停止）、`cafe_autoplay_gui.py`、`cafe_autoplay_strategy.py`、`../tests/test_cafe_autoplay.py`、`../tests/test_cafe_autoplay_clear.py` |
| バランス予備評価 | `autoplay_evaluation.py`、`../tests/test_autoplay_evaluation.py`、`../Docs/Results/AutoPlayBalanceEvaluation.json` |
| 新規開始・操作・GUI | `cafe_new_game.py`、`cafe_interaction.py`、`cafe_interaction_gui.py` |
| 営業・日次結果 | `core/cafe_interaction.py`、`core/multi_seat_cafe.py` |
| 保存・詳細再生 | `storage/cafe_saves.py`、`core/cafe_checkpoint.py`、`core/cafe_replay.py` |
| 関係・自動接客 | `core/human_cat_relationship.py`、`storage/relationships.py`、`policies/human_cat.py` |
| 派遣・比較 | `core/cafe_activities.py`、`core/cafe_dispatch_unlocks.py`、`core/cafe_dispatch_encounters.py`、`core/cafe_dispatch_match.py`、`cafe_dispatch_comparison.py` |
| 特性・成長・出勤予測 | `core/cafe_traits.py`、`core/cafe_growth.py`、`cafe_shift_forecast.py` |
| 加入・飼育 | `core/cafe_recruitment.py`、`core/cafe_dispatch_introduction.py`、`core/cafe_regular_introduction.py`、`core/cafe_housing.py` |
| 設備・用品・収支 | `core/cafe_equipment.py`、`core/cafe_seat_equipment.py`、`core/cafe_items.py`、`core/cafe_item_sales.py`、`core/cafe_finance.py` |

## 互換性と検証

営業セーブ形式2・チェックポイント1・詳細リプレイ4を維持しています。旧セーブの猫・顧客ID、提示済み候補、固定設定、出発済み派遣と設備効果を維持し、新規専用ルールを自動で後付けしません。一部機能は旧ゲームの新しい購入・出発から利用できるため、個別仕様の適用範囲を確認してください。

GUI「10日間おまかせ」追加後、全1,085件成功（310.294秒）。追加7件では各段階での停止、10日上限とGUIの応答、方針選択、期限切れ・ゲームオーバー、中止後の保存再開、タイマー取り消し、通常操作への復帰、保存失敗・ログ書き出しを検証しました。ボタンは営業タブに配置し、最小サイズでの既存案内欄の表示を維持しています。ゲームの数値や保存形式は変更していません。当時は113件のMarkdown・1,144件のローカルリンクと差分を確認しました。過去の検証件数は履歴に残しています。

比較評価時は集計テスト5件成功（2.948秒）、クリア自動プレイテスト8件成功（33.147秒）。中間案と長めの案は各3条件の実行結果を評価資料とJSONに保存しました。

直前の設定反映では新規ゲームテスト10件成功（3.232秒、追加3件）。新規全4モードの採用値、旧目標の保存・段階移行・詳細再生、旧他モード全3種類からの途中挑戦を確認しました。新しい通常設定のクリア自動プレイテスト8件成功（101.032秒）、集計テスト5件成功（3.065秒）。GUIのおまかせは最大10日を維持し、旧条件の評価には `--goal-preset legacy` を指定できます。

直前の設定反映後はGUI込み全1,093件成功（359.338秒）。標準期限に依存していた短期テストは条件を明示し、長めの通常設定と分けて確認しました。134件のMarkdown・1,172件のローカルリンクにリンク切れがなく、差分も確認しました。

今回の判断一覧追加は、関連テスト32件（追加7件）成功。判断通知4件（0.380秒）、基礎営業10件（3.691秒）、クリア方針8件（89.805秒）、GUI込みおまかせ10件（1.098秒）で、表示による状態・操作・既存ログの非変更、判断根拠、購入失敗、中止・再開始、600×480の表示を確認しました。今回のGUI全体テストは再実行していません。

```bash
python3 -m unittest discover -s tests -p test_cafe_autoplay_decisions.py
xvfb-run -a env CAT_CAFE_TEST_GUI=1 python3 -m unittest discover -s tests -p test_cafe_autoplay_gui.py
python3 -m unittest discover -s tests -p test_autoplay_evaluation.py
python3 -m unittest discover -s tests
xvfb-run -a env CAT_CAFE_TEST_GUI=1 python3 -m unittest discover -s tests
```

GUI検証は仮想ディスプレイを使います。サンドボックス内のXソケットで接続に失敗した場合は、承認された外部実行を使用します。

前回の名前統一は、名簿テスト6件、猫の詳細・出来事テスト9件、GUIテスト77件の計92件成功。固定名と客層の分離、旧関係ファイルの非更新と保存再開、最小サイズの名簿、表示名から正しいIDへの担当割り当て、譲渡履歴の名前を確認しました。全件テストは今回再実行していません。

通常客増加の比較は、同じシード0で増加なし／4人追加のクリア・増設なし・基礎営業、2人追加のクリアを実行しました。クリア方針は39→40日、席利用率40.0→43.9％、待機期限切れ59→90件。増設なしも43日で完走、基礎営業は20日で同じ期限切れです。4人追加を採用し、猫不足時の待機増加も評価資料に記載しました。詳細と日次JSONは[通常客増加](HumanToCatPopularCustomerGrowth.md#比較結果シード0)を参照してください。

通常客増加ではGUI込み全1,113件を実行（373.896秒）。名簿の案内追加で最小サイズの一覧が狭くなった3件を、案内を見出しにまとめて修正しました。最後の表示修正後はGUI77件（6.350秒）と追加客9件の計86件を再実行して全件成功し、全体の再実行は行っていません。前回の名前変更に追従していなかった譲渡先・増設客の期待値も更新しました。短期の6〜8席テストは旧来店条件を明示し、新しい増設客と追加通常客の併存は別の実来店・保存・再生テストで確認しています。125件のMarkdown・1,189件のローカルリンクにリンク切れがなく、差分も確認しました。
