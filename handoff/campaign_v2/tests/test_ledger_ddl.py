"""Smoke checks of reference DDL only, not an implemented production ledger."""
import sqlite3
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DDLTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript((ROOT/'templates'/'runtime_ledger.sql').read_text())
        self.db.execute("INSERT INTO campaign_revisions VALUES ('c',1,'{}','hash','t')")
        self.db.execute("INSERT INTO accounts VALUES ('paper','a','{}','v1')")
        self.db.execute("INSERT INTO grants VALUES ('g','c',1,'fixture','hash',1,'fixture','t',NULL)")
        self.db.execute("INSERT INTO decisions VALUES ('d','c',1,'hash',1,'PASS','{}','t')")
        self.db.execute("INSERT INTO intents VALUES ('i','d','g','paper','a','client','RESERVED','{}','t')")
        self.db.execute("INSERT INTO broker_orders VALUES ('paper','a','o','i',NULL,'OPEN','fixture')")
        self.db.commit()
    def tearDown(self):self.db.close()
    def test_schema_foreign_keys_enabled(self):self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0],1)
    def test_fill_identity_is_unique_per_account(self):
        row=('paper','a','f','o','1','10','0.04','USD','t','t','fixture')
        self.db.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?)',row)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?)',row)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fills').fetchone()[0],1)
    def test_unknown_intent_reservation_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("INSERT INTO reservations VALUES ('r','missing','cash','1','held',NULL)")
    def test_reservation_rolls_back_with_transaction(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                self.db.execute("INSERT INTO reservations VALUES ('r','i','cash','20.08','held',NULL)")
                raise RuntimeError('Injected transaction interruption')
        self.assertEqual(self.db.execute('SELECT count(*) FROM reservations').fetchone()[0],0)
    def test_money_strings_survive_without_float_conversion(self):
        self.db.execute("INSERT INTO reservations VALUES ('r','i','cash','0.000000000000000001','held',NULL)")
        self.assertEqual(self.db.execute('SELECT amount_decimal FROM reservations').fetchone()[0],'0.000000000000000001')
if __name__=='__main__':unittest.main()
