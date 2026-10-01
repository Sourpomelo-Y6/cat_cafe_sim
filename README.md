# 猫カフェシミュレーター

猫の出勤・休養・派遣を計画し、自動接客の成果で店を発展させるシミュレーターです。新規ゲームでは人気3段階、有力者の満足度、猫6匹との好感度、自由営業から目標を選べます。

## 起動と資料

通常のゲームを起動するには、プロジェクトのルートで次を実行してください。Python 3.12で動作確認しています。

```bash
python3 -m cat_cafe_sim.cafe_interaction gui
```

開始画面で新規ゲームかセーブ再開を選びます。通常営業では猫と席の割り当てを判断し、交流コマンドは自動で進みます。人気目標に挑戦中は「営業」タブの「10日間おまかせ…」で方針を選び、日本語ログを見ながら最大10日進められます。各段階の達成・期限切れ・ゲームオーバーで停止し、中止後は通常操作へ戻れます。

| 知りたいこと | 資料 |
| --- | --- |
| 資料全体から探す | [ドキュメント索引](Docs/README.md) |
| 現在遊べる機能と一日の流れ | [全体計画](Docs/HumanToCatGameFlowPlan.md)、[画面構成](Docs/HumanToCatUIFlow.md) |
| 開発を引き継ぐ | [引き継ぎ資料](Docs/DevelopmentHandoff.md) |
| 今後の機能候補 | [実装予定](Docs/HumanToCatPlannedFeatures.md) |
| 人気目標と期限を増やした場合の比較 | [人気目標・期限の評価](Docs/HumanToCatPopularityDurationEvaluation.md) |
| 自動プレイ5条件の比較結果・調整候補 | [バランス予備評価](Docs/HumanToCatAutoPlayBalanceEvaluation.md) |
| 自動プレイ・ログ・GUI連携とバランス調整の相談 | [自動プレイ計画](Docs/HumanToCatAutoPlayPlan.md)（CLI2モード実装済み） |
| 保存形式と旧セーブの扱い | [営業セーブ](Docs/HumanToCatCafeSaves.md)、[軽量形式](Docs/HumanToCatCompactSaves.md) |
| 追加機能の経緯 | [整理前の資料](Docs/History/README.md) |

## 現在のゲーム機能

| 分野 | 実装済みの内容 |
| --- | --- |
| 猫と活動 | 詳細・できごと履歴、出勤・休養・療養とストレス予測、6種類の特性、プレイヤー交流、活動経験と得意分野・最大3つの交流分類と最初の分類で最大2行動・2つ目の分類で最大2行動・3つ目の分類で最大2行動の個別熟練 |
| 加入と飼育 | 18候補・6回巡回の保護猫紹介と絞り込み、受け入れ依頼、ペットショップ購入、商店街・撮影スタジオ・常連からの紹介、6→9→12匹への飼育枠拡張 |
| 施設と経営 | 2〜8席への増設、休養の強化と防音改修・待合・5種類の接客設備、4種類のケア用品、運営費と日次・期間収支 |
| お客さん | 曜日別来店、特徴との相性、満足評価、常連・累積不満・信頼回復、白猫好き・曜日を分けた静かな交流客・遊び客・日曜の触れ合い客・確率来店の長毛好き客・予約・VIP客 |
| 派遣とイベント | 段階解放、歓迎条件と報酬、撮影スタジオ・用品体験会・美術館などの専用選択イベントと用品報酬、店舗イベント、山あいの宿だけの家出トラブル |
| 目標と保存 | 3種類のクリア目標と自由営業、共通クリア記録、資金・人気のゲームオーバー、途中保存と詳細リプレイ |

機能ごとの条件・暫定数値・互換方針は[ドキュメント索引](Docs/README.md)から各仕様を参照してください。旧セーブへの適用は機能ごとに異なり、新規機能を一括で後付けするものではありません。

## 開発用CLIと検証

通常ゲームのテストはプロジェクトのルートから実行します。GUIを含む検証は仮想ディスプレイを使用します。

```bash
python3 -m unittest discover -s tests
xvfb-run -a env CAT_CAFE_TEST_GUI=1 python3 -m unittest discover -s tests
```

人気目標のテスト用自動プレイは、操作と判断理由を表示し、専用フォルダへセーブとログを保存します。基礎営業（`basic`、既定）と、投資・予測・予約を使うクリア方針（`clear`）を選べます。

```bash
python3 -m cat_cafe_sim.cafe_autoplay --mode basic --days 30
python3 -m cat_cafe_sim.cafe_autoplay --mode clear --days 30
```

通常ゲームとは別に、1日営業CLIとPhase 2の学習環境があります。

```bash
python3 -m cat_cafe_sim run --seed 42 --output reports/day.json
python3 -m cat_cafe_sim replay reports/day.json
```

学習・診断・単独交流などの詳しい実行例は[従来のREADME](Docs/History/2026-10-01/READMEUpdates.md#開発用CLIと検証)と[資料索引](Docs/README.md)を参照してください。履歴の仕様・検証件数は記録当時のものです。

## 今後の作業

テスト用自動プレイの2つの判断方針と日本語ログを実装しました。GUI「10日間おまかせ」も実装済みで、通常設定・シード0の5条件を比較した[バランス予備評価](Docs/HumanToCatAutoPlayBalanceEvaluation.md)も追加しました。再実行は `python3 -m cat_cafe_sim.autoplay_evaluation`。採用した長めの案（人気250→450→650、期限20・20・25日、上限650）を新規ゲームへ反映しました。旧セーブの目標・期限・上限は維持します。その他の数値調整と対象拡張は後続です。[自動プレイ計画](Docs/HumanToCatAutoPlayPlan.md)に希望と提案を整理しています。
