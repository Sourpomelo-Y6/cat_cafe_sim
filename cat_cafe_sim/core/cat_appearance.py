"""画像制作向けの外見。空文字は未設定、ゲームの相性とは独立。"""
FIELDS = {'eye_color': '目の色', 'body_type': '体格', 'markings': '模様の詳細',
          'face_shape': '顔立ち', 'tail': '尻尾', 'notes': '外見の補足'}


def validate_appearance(value):
    if not isinstance(value, dict) or not set(value) <= set(FIELDS):
        raise ValueError('外見プロフィールの項目が不正です。')
    if any(not isinstance(text, str) or len(text) > 1000 for text in value.values()):
        raise ValueError('外見は各項目1000文字以内の文字列で指定してください。')
    return {key: value.get(key, '').strip() for key in FIELDS}
