"""Exact arithmetic illustrations only; no trading strategy is evaluated."""
from decimal import Decimal
import unittest
from tools.contract_checks import ContractError,amount,funded_quantity,round_trip_net,flow_adjusted_pnl
class ArithmeticTests(unittest.TestCase):
    def test_equal_notional_maker_maker_fees(self):
        self.assertEqual(round_trip_net('1','100','100','0.004','0.004'),Decimal('-0.8'))
    def test_equal_notional_maker_taker_fees(self):
        self.assertEqual(round_trip_net('1','100','100','0.004','0.008'),Decimal('-1.2'))
    def test_equal_notional_taker_taker_fees(self):
        self.assertEqual(round_trip_net('1','100','100','0.008','0.008'),Decimal('-1.6'))
    def test_gross_win_can_be_net_loss(self):
        self.assertLess(round_trip_net('1','100','100.5','0.004','0.008'),0)
    def test_fee_positive_control_can_be_net_gain(self):
        self.assertGreater(round_trip_net('1','100','102','0.004','0.008'),0)
    def test_funded_quantity_includes_fees_and_rounds_down(self):
        q=funded_quantity('100','10','0.004','0.01')
        self.assertEqual(q,Decimal('9.96'))
        self.assertLessEqual(q*Decimal('10')*Decimal('1.004'),100)
        self.assertGreater((q+Decimal('0.01'))*Decimal('10')*Decimal('1.004'),100)
    def test_fractional_quantity_not_equity_integer(self):
        q=funded_quantity('1','3','0','0.0001');self.assertEqual(q,Decimal('0.3333'))
    def test_zero_cash_zero_quantity(self):self.assertEqual(funded_quantity('0','10','0.004','0.01'),0)
    def test_zero_price_not_infinite_size(self):
        with self.assertRaises(ContractError):funded_quantity('100','0','0','1')
    def test_invalid_decimal_inputs(self):
        for x in ['NaN','Infinity','-1','1e6',' 2',True,2.0]:
            with self.subTest(value=x),self.assertRaises(ContractError):amount(x)
    def test_deposit_not_profit(self):self.assertEqual(flow_adjusted_pnl('100','200','100','0'),0)
    def test_withdrawal_not_trading_loss(self):self.assertEqual(flow_adjusted_pnl('100','50','0','50'),0)
    def test_profit_with_external_cash_flow(self):self.assertEqual(flow_adjusted_pnl('100','210','100','0'),10)
if __name__=='__main__':unittest.main()
