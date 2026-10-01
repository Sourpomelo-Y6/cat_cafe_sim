# 開発引き継ぎ

更新日：2026-10-01。基礎営業を維持したクリア方針・テスト・関連資料を追加しました。実装前の基準コミットは `22451c0`（モード追加方針の資料化）です。

現行機能と一日の流れは[全体計画](HumanToCatGameFlowPlan.md)、詳細仕様は[資料索引](README.md)、未着手候補は[実装予定](HumanToCatPlannedFeatures.md)を参照してください。過去の変更説明・コミット一覧・検証経緯は[整理前の引き継ぎ](History/2026-10-01/DevelopmentHandoff.md)と[履歴索引](History/README.md)へ保存しました。履歴内の「未コミット」「次の作業」は現在の指示ではありません。

## 次の検討事項

ユーザーはテスト用自動プレイの導入、実行内容が見える日本語ログ、将来のGUIで約10日まとめて進める機能、バランス調整を希望しています。[自動プレイ計画](HumanToCatAutoPlayPlan.md)に会話と設計案を整理しています。人気目標のCLI初版・日本語ログは実装済みで、GUI連携とバランス調整は後続です。

初版は人気3段階の進行と正常終了・停止理由・保存再開の一致を確認します。GUIは後続とし、共通の判断処理を利用する案。バランス調整は自動プレイの実行結果を比較して検討します。直前の「派遣比較に帰還後の疲労・ストレス予測を追加」は未着手で、いったん置く案を提示しています。

基礎営業（`basic`）を既定のまま維持し、予測・投資・予約を使うクリア方針（`clear`）を追加しました。数値変更なしで通常設定の人気3段階を16日目に達成することを確認しています。再開時も `clear` を指定して利用します。今後は両方針の結果を使うバランス調整やGUI連携を検討します。[詳細方針](HumanToCatAutoPlayPlan.md#基礎営業とクリアを目指すモード)を参照してください。

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
| テスト用自動プレイ | `cafe_autoplay.py`（`AutoPlayer.step()`・CLI）、`cafe_autoplay_strategy.py`、`../tests/test_cafe_autoplay.py`、`../tests/test_cafe_autoplay_clear.py` |
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

クリア方針追加後、GUIを含む全1,078件成功（305.314秒）。追加8件では通常設定のクリア・基礎営業の従来結果、予備資金、各操作後の保存再開一致、購入後の中断再開、予測の下限、投資・予約の期限境界、詳細リプレイを検証しました。通常設定では基礎営業は16日目に第2段階の期限切れ、クリア方針は4・9・16日目に各段階を達成しました。ゲームの数値や保存形式は変更していません。113件のMarkdown・1,143件のローカルリンクと差分を確認済みです。過去の検証件数は履歴に残しています。

```bash
python3 -m unittest discover -s tests
xvfb-run -a env CAT_CAFE_TEST_GUI=1 python3 -m unittest discover -s tests
```

GUI検証は仮想ディスプレイを使います。サンドボックス内のXソケットで接続に失敗した場合は、承認された外部実行を使用します。
