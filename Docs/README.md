# ドキュメント索引

更新日：2026-09-30

通常ゲームの概要は[全体計画](HumanToCatGameFlowPlan.md)、開発再開は[引き継ぎ](DevelopmentHandoff.md)、未着手の候補は[実装予定](HumanToCatPlannedFeatures.md)から読みます。起動・実行例は[リポジトリのREADME](../README.md)を参照してください。

個別機能の現行ルール・数値・旧セーブへの適用範囲は、各仕様の記述を優先します。「初期設計・提案・実装経緯」と「旧営業CLI・学習環境」の資料は当時の対象・版に関する記録で、通常ゲーム全体の最新仕様ではありません。資料中の検証件数は実施時点の結果です。

## 入口・現行計画

- [開発引き継ぎ](DevelopmentHandoff.md)
- [ゲーム全体の流れと実装状況](HumanToCatGameFlowPlan.md)
- [未着手機能と検討事項](HumanToCatPlannedFeatures.md)
- [施設発展・来客増加・高難度のお客さん](HumanToCatStoreDevelopmentPlan.md)
- [猫の加入経路と後続計画](HumanToCatRecruitmentPlan.md)

## 開始・画面・通常営業

- [新規ゲーム・セーブ再開・終了後の再開始](HumanToCatNewGame.md)
- [新規ゲーム開始時の目標選択](HumanToCatObjectiveSelection.md)
- [自由営業・好感度・有力者モードから人気3段階へ挑戦](HumanToCatPopularityChallenge.md)
- [通常営業UIの構成](HumanToCatUIFlow.md)
- [営業の割り当てと自動交流](HumanToCatAutomaticCafe.md)
- [お客さんの名簿と当日の来店予定](HumanToCatCustomers.md)
- [閉店結果と翌日の営業](HumanToCatCafeDays.md)
- [店舗の休業日と翌日へのスキップ](HumanToCatCafeDayOffPlan.md)

## 猫・関係・活動

- [猫の詳細画面：初回実装と後続計画](HumanToCatCatDetailsPlan.md)
- [猫の経験・得意分野と接客熟練](HumanToCatCatGrowthPlan.md)
- [猫の名前・個性の登録と再会](HumanToCatCatProfiles.md)
- [関係一覧からの再会](HumanToCatRelationshipList.md)
- [親しみの段階と再会時の表現](HumanToCatRelationshipPresentation.md)
- [出勤・休養と長期疲労](HumanToCatCafeShifts.md)
- [疲労による病気と療養・復帰](HumanToCatCafeHealth.md)
- [猫の特性：初回仕様](HumanToCatTraits.md)
- [猫の特徴とお客さんの好み：初回仕様](HumanToCatCustomerPreferences.md)
- [プレイヤーと猫のコマンド交流](HumanToCatPlayerInteraction.md)
- [保護猫の譲渡イベント：初回仕様](HumanToCatAdoption.md)
- [ストレス・家出・帰還と経営終了：初回仕様](HumanToCatManagement.md)

## 加入・派遣・用品

- [保護猫の受け入れ：初回仕様](HumanToCatRecruitment.md)
- [保護猫の受け入れ依頼イベント](HumanToCatIntakeRequest.md)
- [ペットショップで猫を迎える](HumanToCatPetShop.md)
- [飼育スペースと受け入れ上限](HumanToCatHousing.md)
- [猫の活動状態・派遣と帰還イベント](HumanToCatCafeActivities.md)
- [猫の運動教室への派遣](HumanToCatExerciseDispatch.md)
- [派遣中の選択イベント](HumanToCatDispatchEncounters.md)
- [派遣先からの猫紹介](HumanToCatDispatchIntroduction.md)
- [常連のお客さんからの猫紹介](HumanToCatRegularIntroduction.md)
- [店先に通う猫との交流・加入](HumanToCatVisitingCat.md)
- [山あいの宿への派遣と家出トラブル](HumanToCatDispatchTrouble.md)
- [ケア用品・栄養おやつの購入・売却、派遣報酬と猫のケア](HumanToCatItems.md)

## 施設・経営・顧客

- [店の段階的な増設：2席から7席へ](HumanToCatExpansion.md)
- [席ごとの接客設備](HumanToCatSeatEquipment.md)
- [休養設備：休養スペース](HumanToCatRestEquipment.md)
- [待合スペースの施設強化](HumanToCatWaitingArea.md)
- [日次の店舗運営費](HumanToCatOperatingCosts.md)
- [日次収支と期間比較](HumanToCatDailyFinance.md)
- [店舗ランダムイベント](HumanToCatStoreEvents.md)
- [曜日別の来店と今日・翌日の予定](HumanToCatWeekdays.md)
- [1回ごとの接客評価](HumanToCatCustomerSatisfaction.md)
- [お客さんの常連度と週1回の追加来店](HumanToCatCustomerLoyalty.md)
- [お客さんの累積不満と一時的な来店停止](HumanToCatCustomerDiscontent.md)
- [お客さんの信頼回復と永久離脱](HumanToCatCustomerTrust.md)
- [白猫好きのこだわり客](HumanToCatAdvancedCustomers.md)
- [静かに過ごしたいお客さん](HumanToCatQuietCustomer.md)
- [遊び好きのお客さん](HumanToCatPlayCustomer.md)
- [触れ合い好きのお客さん](HumanToCatContactCustomer.md)
- [人気第2段階で解放する特別予約](HumanToCatReservations.md)
- [人気最終段階で解放するVIP客](HumanToCatVipCustomer.md)

## 目標・保存・交流仕様

- [人気の獲得と期限付きクリア目標：3段階](HumanToCatPopularityGoal.md)
- [有力者への派遣と満足度目標](HumanToCatPatronGoal.md)
- [猫との好感度目標：6匹](HumanToCatBondGoal.md)
- [共通のクリア結果・記録画面](HumanToCatClearResults.md)
- [営業途中の保存と再開](HumanToCatCafeSaves.md)
- [営業セーブの軽量化](HumanToCatCompactSaves.md)
- [8種類の交流と猫の個性：暫定仕様](HumanToCatInteractionTypes.md)
- [テンションと特別行動：初回実装用の暫定仕様](HumanToCatSpecialActionsSpecification.md)
- [親しみの持ち越しと交流成果：初回実装用の暫定仕様](HumanToCatRelationshipSpecification.md)

## 検証・評価の記録

測定時の条件と結果を保持します。新機能追加後の再測定結果として扱わないでください。

- [長期営業のバランス検証](HumanToCatLongTermEvaluation.md)
- [疲労を優先した休養・割り当ての比較](HumanToCatFatiguePriorityEvaluation.md)
- [個性ごとの成功経路と反応方策の診断](HumanToCatReachabilityAnalysis.md)

## 初期設計・提案・実装経緯

旧仕様・案・初回実装を含みます。現在の実装状態は上の全体計画と機能別仕様を参照してください。

- [猫カフェシミュレーションゲーム：Codex向け実装資料](CatCafeSimulation_ImplementationGuide.md)
- [猫カフェゲームへのプロトタイプ活用・引き継ぎ方針](CatCafePrototypeReusePlan.md)
- [お客さんの特性と猫の特徴・相性の案](HumanToCatCustomerPreferencesPlan.md)
- [HumanToCatActionProposal](HumanToCatActionProposal.md)
- [人の動作と猫の反応：接客行動の設計案](HumanToCatInteractionDesign.md)
- [交流の目的・終了・成果の見直し](HumanToCatInteractionPurpose.md)
- [交流の拡張案：テンション・特別行動・動作種類](HumanToCatSpecialActions.md)
- [人と猫の単独交流：初期実装と検証結果](HumanToCatInteractionImplementation.md)
- [8種類の交流と猫の個性：版3の実装記録](HumanToCatInteractionTypesImplementation.md)
- [テンションと特別行動：版2の実装記録](HumanToCatSpecialActionsImplementation.md)
- [親しみ・終了・成果・再会：版4の実装記録](HumanToCatRelationshipImplementation.md)
- [単独交流と営業の接続：初回仕様・実装](HumanToCatCafeIntegration.md)
- [複数の猫から担当を選ぶ営業](HumanToCatCafeRoster.md)
- [2席での同時交流とテスト用の猫](HumanToCatMultiSeatCafe.md)
- [人と猫の交流：試遊画面](HumanToCatPlaytestUI.md)

## 旧営業CLI・学習環境の記録

- [Phase 1 実装状況](Phase1_ImplementationStatus.md)
- [Phase 2 接客ルール・環境の実装](Phase2_InteractionFoundation.md)
- [Phase 2 猫方策の離散化・Q学習](Phase2_QLearning.md)
- [学習済み猫の1日営業への接続](Phase2_LearnedCafePolicy.md)
- [接客開始時の体力・気力・残り時間の指定](Phase2_InteractionStart.md)
- [開始条件を混ぜた猫方策の再学習と営業比較](Phase2_MixedStartTraining.md)
- [Phase 2: 失敗分析と体力区間の比較](Phase2_FailureAnalysis.md)

## 整理前の履歴

[履歴索引](History/README.md)に、重複した追記・原案・旧実装順を保存しています。整理前のファイル名と本文を残し、リンクは移動先に合わせて修正しました。

## 更新の分担

新機能は機能別仕様へ条件・操作・保存・検証を書き、全体計画の該当行と引き継ぎを更新します。未着手候補は実装予定で管理し、実装後は現行仕様へのリンクへ置き換えます。READMEには入口と概要を置き、同じ日付の変更説明を複数の計画へ積み重ねません。
