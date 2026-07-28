import unittest

from scripts import sa_collect


class PreferredDividendFilterTests(unittest.TestCase):
    def test_preferred_dividend_news_is_filtered(self):
        cases = [
            ("BAC.PR.S", "BAC: Bank of America Corporation 4.750% DP PFD SS declares $0.2968 dividend"),
            ("BAC", "BAC: Bank of America Corporation Deposit Shs Perp Pfd Shs Series E declares $0.2723 dividend"),
            ("BML.PR.G", "BAC: Bank of America Deposit shs Repr 1/1200th Fltg Rate Non-Cum Pfd Shs Series 1 declares $0.29 dividend"),
            ("BAC.PR.B", "BAC: Bank of America Corporation 6 NCUM PFD SR GG declares $0.375 dividend"),
        ]
        for ticker, subject in cases:
            self.assertTrue(
                sa_collect.is_preferred_dividend(subject, ticker),
                msg=f"should filter: {subject}",
            )

    def test_common_and_nondividend_news_are_kept(self):
        keep = [
            ("AAPL", "AAPL: Apple Inc. declares $0.25 dividend"),        # 일반주 배당
            ("KO", "KO: Coca-Cola declares $0.485 dividend"),
            ("TSLA", "TSLA: Tesla unveils new Model Y refresh"),          # 비배당
            ("RMS.PA", "RMS.PA: Hermes reports Q2 sales beat"),          # .PA(파리)는 우선주 아님
            ("MSFT", "MSFT: Microsoft raises quarterly dividend by 10%"),
        ]
        for ticker, subject in keep:
            self.assertFalse(
                sa_collect.is_preferred_dividend(subject, ticker),
                msg=f"should keep: {subject}",
            )


class EarningsPreviewFilterTests(unittest.TestCase):
    def test_earnings_preview_is_filtered(self):
        drop = [
            "PYPL: PayPal's Q2 earnings estimated to be hit on lower margin despite rise in payment volume",
            "HLT: Hilton Worldwide Q2 2026 Earnings Preview",
            "INTC: Intel earnings setup: Options market prices in double-digit move",
            "DECK: Here are the major earnings after the close Thursday",
            "AXP: All eyes on American Express Q2 earnings: Will card spending offset rising costs?",
            "INTC: Intel is on the radar; what will be said in its upcoming earnings call?",
            "Ford heads into Q2 earnings after double-digit sales decline",
            "TSLA: Tesla enters earnings with shorts piling in, technicals weakening: S3 Partners",
            "GOOGL: Alphabet may move 5.4% on earnings report",
            "Mastercard, Visa earnings to shed light on consumer spending this week",
        ]
        for subject in drop:
            self.assertTrue(sa_collect.is_earnings_preview(subject), msg=f"should filter: {subject}")

    def test_actual_earnings_results_are_kept(self):
        keep = [
            "VZ: Verizon holds near flat after Q2 earnings beat and guidance boost",
            "LMT: Lockheed Martin raises 2026 outlook after Q2 earnings beat, shares climb",
            "Tenet Healthcare surges on Q2 earnings beat, lifts full-year guidance",
            # 'ahead of earnings'는 실제 뉴스의 꼬리 문구 → 유지해야 함
            "TSLA: Tesla adds Orlando and Tampa to robotaxi service network ahead of earnings",
            "STX: Seagate, Western Digital in focus as Wedbush ups price targets ahead of earnings",
            "GOOGL: Earnings scorecard: Communication sector sees 4 of 6 stocks top EPS estimates",
        ]
        for subject in keep:
            self.assertFalse(sa_collect.is_earnings_preview(subject), msg=f"should keep: {subject}")


class FundHoldingsFilterTests(unittest.TestCase):
    def test_fund_disclosure_is_filtered(self):
        drop = [
            "ADBE: Polaris Global Equity Composite adds new holdings, exits multiple positions in Q2",
            "ClearBridge ESG Strategy adds SpaceX, AMD, and Micron; exits Roblox, AbbVie",
            "Parnassus Value Equity Fund adds KO; exits BIO",
            "HESAY: Wedgewood Partners adds Hermès, exits Tractor Supply, Zoetis in Q2",
            "NKE: Fundsmith adds AppLovin, TSMC, Uber; exits Nike, LVMH among 1H moves",
            "ECHO: The Nightview Fund exits Meta, Shopify; buys Las Vegas Sands and MGM in Q2",
        ]
        for subject in drop:
            self.assertTrue(sa_collect.is_fund_holdings_news(subject), msg=f"should filter: {subject}")

    def test_company_and_market_news_are_kept(self):
        keep = [
            # 사명이 'Strategy'인 MSTR — 실제 기업 뉴스
            "MSTR: Strategy didn't buy or sell any bitcoin last week",
            "BX: Blackstone, Wellington, Vanguard alliance launch two investment funds",
            "SOXX: Hedge funds dump U.S. tech stocks at record clip - Goldman",
            "GS: Goldman Sachs private credit fund gets redemption requests of 3.24% in Q2",
            "ANTHRO: Abu Dhabi-based AI investment firm MGX raises $49B for its Fund I",
        ]
        for subject in keep:
            self.assertFalse(sa_collect.is_fund_holdings_news(subject), msg=f"should keep: {subject}")


class CoverageInitiationFilterTests(unittest.TestCase):
    def test_coverage_initiation_is_filtered(self):
        drop = [
            "CRWD: CrowdStrike in focus as Loop Capital starts coverage with Buy rating",
            "Rigetti, IonQ, D-Wave Quantum in focus as Benchmark starts coverage",
            "ARM: Arteris receives Outperform rating as Oppenheimer initiates coverage",
            "VRT: Vertiv rated Outperform in new coverage at Baird on data center demand",
            "BWXT: BWX Technologies initiated Overweight at J.P. Morgan",
            "CRWV: CoreWeave, Nebius initiated with Outperform ratings at Baird",
            "TSLA: Tesla initiated at Market Perform on concerns over near-term AI",
            "SPCX: SpaceX sinks despite flurry of bullish analyst initiations",
        ]
        for subject in drop:
            self.assertTrue(sa_collect.is_coverage_initiation(subject), msg=f"should filter: {subject}")

    def test_other_coverage_and_initiates_are_kept(self):
        keep = [
            # 보험·의약품 급여, 통신망 커버리지
            "LLY: Cigna reportedly dropping GLP-1 obesity drug coverage for its own employees",
            "CVS Health reintroduces coverage for Lilly's Zepbound",
            "UNH: Guardant Health rises following UnitedHealth coverage of Shield test",
            "AT&T reaffirms profit targets, goal of 60M fiber internet coverage by 2030",
            # 기업 행위로서의 initiates / initiatives
            "BSX: Boston Scientific initiates new restructuring plan",
            "INTC: Intel initiates new round of layoffs centering on its data center group",
            "AAPL: India commits about $20B for chip, smartphone initiatives",
            # 등급 변경·목표주가는 유지
            "AT&T upgraded by Wolfe Research as improving fundamentals outweigh competitive risks",
            "STX: Seagate, Western Digital in focus as Wedbush ups price targets",
        ]
        for subject in keep:
            self.assertFalse(sa_collect.is_coverage_initiation(subject), msg=f"should keep: {subject}")


class ExcludedReasonTests(unittest.TestCase):
    def test_reason_labels(self):
        cases = [
            ("BAC.PR.S", "BAC: Bank of America 4.750% DP PFD SS declares $0.2968 dividend", "우선주배당"),
            ("HLT", "HLT: Hilton Worldwide Q2 2026 Earnings Preview", "실적프리뷰"),
            ("PGVFX", "ADBE: Polaris Global Equity Composite adds new holdings, exits positions in Q2", "펀드공시"),
            ("CRWD", "CRWD: CrowdStrike in focus as Loop Capital starts coverage with Buy rating", "커버리지개시"),
            ("AAPL", "AAPL: Apple unveils new MacBook Pro lineup", None),
        ]
        for ticker, subject, expected in cases:
            self.assertEqual(sa_collect.excluded_reason(subject, ticker), expected, msg=subject)


if __name__ == "__main__":
    unittest.main()
