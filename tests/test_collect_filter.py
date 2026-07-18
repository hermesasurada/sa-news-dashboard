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


if __name__ == "__main__":
    unittest.main()
