"""암호화폐 칩(2026-11-24 사용자 지시, sa 12490): 원제·헤드라인의 비트코인·이더리움 → BTC·ETH."""
import foreign_tickers as F
import summary_contract


def test_headline_names_add_chips():
    assert F.supplement_crypto(
        ("COIN: CFTC staff says crypto can count toward reserves but not liquidity buffers",
         "CFTC, Bitcoin·Ether 등 암호화폐 준비금 인정…유동성 요건은 제외"),
        "COIN", "Coinbase Global") == ("COIN, BTC, ETH", "Coinbase Global·Bitcoin·Ethereum")


def test_korean_and_symbol_forms():
    assert F.crypto_from_titles(("Strategy, 비트코인 457개 매입", "총 보유 851K BTC"), ["MSTR"]) == [("BTC", "Bitcoin")]
    assert F.crypto_from_titles(("이더리움 현물 ETF 유입",), []) == [("ETH", "Ethereum")]


def test_no_false_positives():
    for title in ("Goldman Sachs, 트레이더·뱅커의 AI 코딩 도구 사용 제한", "레이더 업체 수주",
                  "Ethernet switch demand", "diethyl ether supply", "BTCS raises capital"):
        assert F.crypto_from_titles((title,), []) == [], title


def test_existing_chip_and_none_placeholder():
    assert F.supplement_crypto(("Bitcoin slips",), "IBIT, BTC", "iShares·Bitcoin") == ("IBIT, BTC", "iShares·Bitcoin")
    assert F.supplement_crypto(("Bitcoin slips 4% below $70K",), "NONE", "") == ("BTC", "Bitcoin")


def test_validate_uses_headline():
    d = summary_contract.validate({"ticker": "COIN", "company_name": "Coinbase Global",
                                   "headline": "CFTC, Bitcoin·Ether 준비금 인정", "summary_details": ["x"]},
                                  original_title="COIN: CFTC staff says crypto can count toward reserves")
    assert d["ticker"] == "COIN, BTC, ETH"
