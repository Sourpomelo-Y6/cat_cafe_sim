# 独立した猫画像制作ツール

制作GUIはゲームとは別の `CatCafeSim/cat_cafe_sim_tool` フォルダに配置しました。ゲームから登録画面を開く機能はありません。

親の `CatCafeSim` フォルダから起動します。

```powershell
python -X utf8 cat_cafe_sim_tool/run.py
```

猫と場面を選び、背景込みPNGをプレビューして登録します。ゲームの起動は不要です。詳細は[制作ツールのREADME](../../cat_cafe_sim_tool/README.md)を参照してください。

標準の保存先はゲーム内の `saves/content_images/`。元画像のコピーと `manifest.json` を保存します。ゲームの「猫の画像…」では、この対応表の読み込みと自動表示だけを行います。未登録・読込失敗時は仮画像を使います。猫IDを一致させてください。

制作ツールの「ComfyUIで生成…」からローカル画像生成を利用できます。プロンプトとseedなどを指定して1枚生成し、候補を確認してから登録します。設定と操作は[制作ツールのREADME](../../cat_cafe_sim_tool/README.md)を参照してください。LLMによる文章生成は未接続です。
