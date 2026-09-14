"""営業画面で共有する体調表示。"""

def health_text(status, remaining):
    return f'療養あと{remaining}日' if status == 'sick' else '健康'


def health_result_text(result):
    labels = {'healthy': '健康維持', 'sick': '発症', 'recovering': '療養中', 'recovered': '回復'}
    return f"{labels[result['outcome']]} · {health_text(result['after'], result['remaining_after'])}"
