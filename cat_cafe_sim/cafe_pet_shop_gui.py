"""固定候補の価格と特徴を比較して猫を購入する。"""
from .cafe_recruitment_gui import CafeRecruitmentWindow


class CafePetShopWindow(CafeRecruitmentWindow):
    def __init__(self, parent, session, on_changed):
        super().__init__(parent, session, on_changed, pet_shop=True)
