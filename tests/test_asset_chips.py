"""자산 칩: 원제·헤드라인의 비트코인·이더리움 → BTC·ETH(2026-11-24, sa 12490), 금 → GLD(2026-11-25, sa 12595)."""
import foreign_tickers as F
import summary_contract


def test_headline_names_add_chips():
    assert F.supplement_asset_chips(
        ("COIN: CFTC staff says crypto can count toward reserves but not liquidity buffers",
         "CFTC, Bitcoin·Ether 등 암호화폐 준비금 인정…유동성 요건은 제외"),
        "COIN", "Coinbase Global") == ("COIN, BTC, ETH", "Coinbase Global·Bitcoin·Ethereum")


def test_korean_and_symbol_forms():
    assert F.asset_chips_from_titles(("Strategy, 비트코인 457개 매입", "총 보유 851K BTC"), ["MSTR"]) == [("BTC", "Bitcoin")]
    assert F.asset_chips_from_titles(("이더리움 현물 ETF 유입",), []) == [("ETH", "Ethereum")]


def test_no_false_positives():
    for title in ("Goldman Sachs, 트레이더·뱅커의 AI 코딩 도구 사용 제한", "레이더 업체 수주",
                  "Ethernet switch demand", "diethyl ether supply", "BTCS raises capital"):
        assert F.asset_chips_from_titles((title,), []) == [], title


def test_existing_chip_and_none_placeholder():
    assert F.supplement_asset_chips(("Bitcoin slips",), "IBIT, BTC", "iShares·Bitcoin") == ("IBIT, BTC", "iShares·Bitcoin")
    assert F.supplement_asset_chips(("Bitcoin slips 4% below $70K",), "NONE", "") == ("BTC", "Bitcoin")


def test_validate_uses_headline():
    d = summary_contract.validate({"ticker": "COIN", "company_name": "Coinbase Global",
                                   "headline": "CFTC, Bitcoin·Ether 준비금 인정", "summary_details": ["x"]},
                                  original_title="COIN: CFTC staff says crypto can count toward reserves")
    assert d["ticker"] == "COIN, BTC, ETH"


def test_gold_adds_gld():
    assert F.supplement_asset_chips(("GLD: China's gold imports said to have surged to record $209B through Oct.",
                                     "중국, 10월까지 금 수입액 $209B로 사상 최대"), "", "") == ("GLD", "SPDR Gold Shares")
    assert F.asset_chips_from_titles(("NVDA: U.S. indexes are mixed after Nvidia earnings; gold declines",), ["NVDA"]) \
        == [("GLD", "SPDR Gold Shares")]
    for ko in ("금, 거의 50년 만에 최악의 11월", "금값 하락", "금·은 선물 급락", "금 선물 보합", "중앙은행 금 매입", "금이 오른다"):
        assert F.asset_chips_from_titles((ko,), []) == [("GLD", "SPDR Gold Shares")], ko
    assert F.supplement_asset_chips(("Gold slips",), "GLD, IAU", "SPDR·iShares") == ("GLD, IAU", "SPDR·iShares")


def test_gold_false_positives():
    for title in ("GLD: Maple Gold retracts internal study disclosures", "Barrick Gold beats estimates",
                  "Gold Fields raises output", "Goldman Sachs 전망", "Golden Ocean 인수",
                  "Fed 금리 인상", "금융주 강세", "자금 유입", "현금 배당", "금요일 마감", "실질금리 상승", "임금 인상",
                  "JPMorgan·HSBC, 런던서 첫 디지털 골드 거래"):
        assert F.asset_chips_from_titles((title,), []) == [], title
