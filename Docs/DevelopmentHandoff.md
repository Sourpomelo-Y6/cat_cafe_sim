# 開発引き継ぎ

更新日：2026-09-30 / 対象：通常の人対猫ゲーム

## 現在の状態

作業フォルダは `/home/hi-wa/learning2/cat_cafe_sim`、ブランチは `main`。最新の機能コミットは `8b95545`（静かに過ごしたいお客さん）。直近の機能はすべてコミット済みです。ドキュメント整理では資料索引と履歴を追加し、現行仕様・後続候補・引き継ぎを整理しました。

現行機能は[全体計画](HumanToCatGameFlowPlan.md)、詳細仕様は[資料索引](README.md)、後続候補は[実装予定](HumanToCatPlannedFeatures.md)を参照してください。整理前の追記と当時の検証結果は[履歴](History/2026-09-30/DevelopmentHandoff.md)に保存しています。

## 開発方針

- ゲーム全体の流れを固めることを優先し、細かな数値バランス調整は後回し。
- エンディングまでの自動プレイは後続。通常の自動接客と区別する。
- スカウトは実装負担が大きいため低優先度で、加入・6匹クリアの必須経路にしない。
- 子猫は所属猫として管理せず、預け先・譲渡費用のみ処理する。
- お詫び費用は採用しない。
- 通常接客のコマンドは自動選択。プレイヤーは割り当て・準備・経営を判断する。
- 実装・検証と関連資料の更新を完了して報告し、コミットは別途依頼を受けて行う。
- 作業ツールが利用できないと断定する前に、実際の呼び出しとエラーを確認する。

## 直近の完了機能

| コミット | 内容 | 仕様 |
| --- | --- | --- |
| `8b95545` | 第1段階達成後の静かな交流客。設備と通常交流3回で追加料金150・人気3 | [静かな交流客](HumanToCatQuietCustomer.md) |
| `688b8d4` | 分類別の接客設備3種類。従来設備・旧設定を維持 | [接客設備](HumanToCatSeatEquipment.md) |
| `3fc5451` | 山あいの宿と、その派遣先だけの家出トラブル | [派遣トラブル](HumanToCatDispatchTrouble.md) |
| `141c2ed` | 固定3匹のペットショップ購入 | [購入](HumanToCatPetShop.md) |
| `a6814ab` | 商店街への派遣からの猫紹介 | [紹介](HumanToCatDispatchIntroduction.md) |
| `3509189` | 保護猫の紹介元12種類と特徴表示 | [受け入れ](HumanToCatRecruitment.md) |
| `404f253` | 6→9匹の飼育スペース拡張。旧セーブは上限なし | [飼育枠](HumanToCatHousing.md) |

その前にはケア用品購入、派遣先の歓迎条件・報酬内訳・段階解放、猫の活動経験と得意分野・3分類の接客熟練、相性を使う自動割り当てを実装済みです。

## 実装の調査先

以下は `cat_cafe_sim/` からの相対パスです。

| 対象 | 主な実装 |
| --- | --- |
| 新規開始・操作 | `cafe_new_game.py`、`cafe_interaction.py`、`cafe_interaction_gui.py` |
| 営業状態・日次結果 | `core/cafe_interaction.py`、`core/multi_seat_cafe.py` |
| 保存・詳細再生 | `storage/cafe_saves.py`、`core/cafe_checkpoint.py`、`core/cafe_replay.py` |
| 関係・自動接客 | `core/human_cat_relationship.py`、`storage/relationships.py`、`policies/human_cat.py` |
| 加入・飼育 | `core/cafe_recruitment.py`、`core/cafe_intake_request.py`、`core/cafe_pet_shop.py`、`core/cafe_dispatch_introduction.py`、`core/cafe_housing.py` |
| 設備・収支 | `core/cafe_seat_equipment.py`、`core/cafe_finance.py`、`core/cafe_operating_cost.py` |
| 静かな交流客 | `core/cafe_quiet_customer.py`、`cafe_customers_gui.py`、`tests/test_cafe_quiet_customer.py`（テストはリポジトリ直下） |

## 互換性と検証

新規専用ルールを旧セーブへ後付けせず、保存済みの猫・顧客ID、固定した候補・条件、既存設備の効果を維持します。一部機能は旧ゲームの新しい購入・出発から適用するため、個別仕様の互換欄を確認してください。

最新の機能検証は `8b95545` の実装時に実施した、仮想ディスプレイでGUIを含む全655件成功です。静かな交流客の追加9件では、解放・条件判定・実際の自動接客・会計と人気・設備移動後の過去結果・保存失敗の再試行・旧セーブ・他モード・リプレイ・不正データ・名簿表示を確認しました。

```bash
python3 -m unittest discover -s tests
xvfb-run -a env CAT_CAFE_TEST_GUI=1 python3 -m unittest discover -s tests
```

GUI検証は仮想ディスプレイを使います。サンドボックス内のXソケットで接続に失敗した場合は、承認された外部実行を使用します。モデル名だけでGUI実行の可否を決めません。

今回の整理はMarkdownだけの変更です。ローカルリンク、索引の網羅性、履歴への原文保存、差分を確認し、ゲームのテストは再実行していません。

## 次の作業

次の機能はユーザーの依頼に沿って進めます。[未着手候補](HumanToCatPlannedFeatures.md)を参照し、以前の履歴に残る「次に実装する」「未コミット」を現在の指示として扱わないでください。
