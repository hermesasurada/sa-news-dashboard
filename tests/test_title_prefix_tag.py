"""제목 앞 티커는 SA 태그일 뿐 — 강제로 칩에 넣지 않고 모델이 관련성으로 판단한다(2026-11-24 사용자 지시, sa 12497)."""
import summary_contract


def test_prefix_ticker_not_forced():
    d = summary_contract.validate({"ticker": "", "company_name": "", "headline": "유럽 증시, 전날 급등 후 혼조세",
                                   "summary_details": ["영국 증시 0.04% 하락"]},
                                  original_title="ANT: European markets flat after strong gains in previous session")
    assert d["ticker"] == ""


def test_model_pick_kept_as_is():
    d = summary_contract.validate({"ticker": "XPO, FDX", "company_name": "XPO·FedEx", "headline": "Citi, XPO 매수 상향",
                                   "summary_details": ["x"]},
                                  original_title="FDX: Citi Research sees opportunities in trucking, upgrades XPO to Buy")
    assert d["ticker"] == "XPO, FDX"


def test_prompt_explains_prefix_tag():
    assert "SA가 단 **태그일 뿐**" in summary_contract._PROMPT_TMPL
