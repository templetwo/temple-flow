"""Contract/fixture tests, not the proposed production runtime acceptance suite."""
from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path
from tools.contract_checks import ContractError, validate_document

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/'examples'/name).read_text())
class ContractTests(unittest.TestCase):
    def campaign(self):return read('campaign.paper_100_to_200.json')
    def intent(self):return read('order_intent.paper.json')
    def decision(self):return read('decision.paper.json')
    def rejected(self,doc):
        with self.assertRaises(ContractError):validate_document(doc)
    def test_all_examples_shape_and_semantics(self):
        for p in sorted((ROOT/'examples').glob('*.json')):
            with self.subTest(path=p.name):validate_document(json.loads(p.read_text()))
    def test_every_campaign_example_is_unarmed(self):
        for p in (ROOT/'examples').glob('campaign.*.json'):
            d=json.loads(p.read_text());self.assertFalse(d['activation']['enabled']);self.assertIsNone(d['activation']['grant_id'])
    def test_full_loss_has_no_inherited_numeric_cap(self):
        d=self.campaign();validate_document(d)
        self.assertFalse(any(x['enabled'] for x in d['optional_limits'].values()))
    def test_missing_rule_not_permission(self):
        d=self.campaign();del d['optional_limits']['daily_loss'];self.rejected(d)
    def test_disabled_rule_cannot_carry_hidden_limit(self):
        d=self.campaign();d['optional_limits']['daily_loss']['limit_fraction']='0.045';self.rejected(d)
    def test_enabled_rule_requires_number(self):
        d=read('campaign.bounded_fixture.json');d['optional_limits']['daily_loss']['limit_fraction']=None;self.rejected(d)
    def test_full_loss_needs_explicit_consent(self):
        d=self.campaign();d['total_allocation_loss_accepted']=False;self.rejected(d)
    def test_full_loss_does_not_keep_four_name_cap(self):
        d=self.campaign();d['optional_limits']['position_count'].update(enabled=True,limit_count=4);self.rejected(d)
    def test_bounded_profile_needs_actual_boundary(self):
        d=self.campaign();d.update(profile='bounded_loss',total_allocation_loss_accepted=False);self.rejected(d)
    def test_unknown_field_rejected(self):
        d=self.campaign();d['override_all_checks']=True;self.rejected(d)
    def test_mode_change_does_not_activate(self):
        d=self.campaign();d['mode']='live';validate_document(d)
        self.assertFalse(d['activation']['enabled']);self.assertIsNone(d['activation']['grant_id'])
    def test_enabled_flag_alone_is_insufficient(self):
        d=self.campaign();d['activation']['enabled']=True;self.rejected(d)
    def test_prepared_needs_balance_snapshot(self):
        d=self.campaign();d['capital']['snapshot_id']=None;self.rejected(d)
    def test_sleeves_reconcile_to_starting_basis(self):
        d=self.campaign();d['capital']['basis_net_usd']='101';self.rejected(d)
    def test_duplicate_account_not_twice_the_capital(self):
        d=self.campaign();d['capital']['venues'].append(copy.deepcopy(d['capital']['venues'][0]));d['capital']['basis_net_usd']='200';self.rejected(d)
    def test_no_automatic_future_deposits(self):
        d=self.campaign();d['capital']['allow_future_deposits']=True;self.rejected(d)
    def test_no_borrowing(self):
        d=self.campaign();d['execution']['borrow']=True;self.rejected(d)
    def test_target_is_not_one_or_less(self):
        d=self.campaign();d['objective']['multiple']='1';self.rejected(d)
    def test_none_objective_has_no_hidden_multiple(self):
        d=self.campaign();d['objective']['kind']='none';self.rejected(d)
    def test_intent_validity_cannot_run_backwards(self):
        d=self.intent();d['expires_at']=d['created_at'];self.rejected(d)
    def test_buy_needs_protective_stop(self):
        d=self.intent();d['protective_stop_price']=None;self.rejected(d)
    def test_long_stop_below_entry(self):
        d=self.intent();d['protective_stop_price']='11';self.rejected(d)
    def test_intent_cannot_reserve_less_than_gross(self):
        d=self.intent();d['max_quote_debit']='19';self.rejected(d)
    def test_entry_must_not_short(self):
        d=self.intent();d['side']='sell';self.rejected(d)
    def test_sell_exit_contract_does_not_require_positive_entry_edge(self):
        d=self.intent();d.update(side='sell',purpose='exit',protective_stop_price=None,max_quote_debit='0');validate_document(d)
    def test_zero_quantity_rejected(self):
        d=self.intent();d['quantity']='0';self.rejected(d)
    def test_float_quantity_rejected(self):
        d=self.intent();d['quantity']=2.0;self.rejected(d)
    def test_fee_unknown_entry_pass_rejected(self):
        d=self.decision();d['fee_snapshot_id']=None;self.rejected(d)
    def test_negative_net_edge_entry_pass_rejected(self):
        d=self.decision();d['net_edge_usd_estimate']='-0.1';self.rejected(d)
    def test_decline_can_record_negative_edge(self):
        d=self.decision();d.update(result='DECLINE',net_edge_usd_estimate='-0.1',reason_codes=['NO_NET_EDGE']);validate_document(d)
    def test_pass_needs_cash(self):
        d=self.decision();d['cash_available_usd']='10';self.rejected(d)
    def test_schema_version_not_guessed(self):
        d=self.campaign();d['schema_version']='campaign.v99';self.rejected(d)
if __name__=='__main__':unittest.main()
