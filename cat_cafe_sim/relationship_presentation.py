"""版4の画面用表現。交流状態や保存データを更新しない。"""
from .core.human_cat_types import bounded

STAGES = ('距離を探っている', '顔なじみ', '親しみが育っている', 'なじみの相手')
REACTIONS = {
    'neutral': (
        '少し離れた場所から、こちらの様子をうかがっています。',
        'こちらに顔を向け、落ち着いて様子を見ています。',
        '近くに腰を下ろし、ゆっくりとまばたきしています。',
        'いつものように近くでくつろいでいます。'),
    'contact': (
        'こちらの手を見ながら、自分のペースで距離を確かめています。',
        'そばに来て、こちらの手のにおいを確かめています。',
        '自分から近寄り、そばに座っています。',
        '自分からそばへ寄り、体をすり寄せています。'),
    'quiet': (
        '離れた場所に座り、静かにこちらを見ています。',
        '少し離れたまま、ゆっくりとまばたきしています。',
        '心地よい距離を保ちながら、こちらのそばで休んでいます。',
        '少し離れたお気に入りの場所で、安心した様子でくつろいでいます。'),
    'active': (
        '少し離れたところから、おもちゃとこちらを見比べています。',
        'こちらに気づくと、おもちゃの方へ歩いていきます。',
        '近くに来て、おもちゃの前でこちらを振り返っています。',
        '慣れた様子でおもちゃのそばに来て、遊びに誘っています。'),
    'sensitive': (
        '距離を取りながら、おもちゃの動きをそっと確かめています。',
        'こちらを見てから、おもちゃへゆっくり近づいています。',
        '近くで落ち着き、小さく動くおもちゃに前足を伸ばしています。',
        'そばでくつろぎながら、穏やかな遊びを待っています。'),
}


def stage_index(affinity):
    bounded(affinity, 0, 100, 'affinity')
    return sum(affinity >= boundary for boundary in (10, 30, 60))


def expression_style(personality):
    values = personality.type_preferences
    scores = {'active': sum(values[:4]) / 4,
              'contact': sum(values[4:6]) / 2,
              'quiet': sum(values[6:]) / 2}
    winners = [key for key, value in scores.items() if value == max(scores.values())]
    if len(winners) != 1:
        return 'neutral'
    style = winners[0]
    if style == 'active' and personality.intensity_preferences[0] > personality.intensity_preferences[2]:
        return 'sensitive'
    return style


def greeting_text(core):
    initial = core.initial_relationship
    index = stage_index(initial['affinity'])
    occasion = '再会' if initial['revision'] else '初対面'
    reaction = REACTIONS[expression_style(core.config.personality)][index]
    return f'{occasion}の様子 · {STAGES[index]}\n{reaction}'


def relationship_change_text(before, after):
    old, new = stage_index(before), stage_index(after)
    if new > old:
        change = '親しみの段階が上がりました。'
    elif new < old:
        change = '親しみの段階が下がりました。'
    elif after > before:
        change = '同じ段階の中で、親しみが増えました。'
    elif after < before:
        change = '同じ段階の中で、親しみが減りました。'
    else:
        change = '親しみは変わりませんでした。'
    return f'関係の目安：{STAGES[old]} → {STAGES[new]}\n{change}'
