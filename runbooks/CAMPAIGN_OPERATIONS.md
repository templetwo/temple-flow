# Campaign operations

**Kraken (this MacBook):** live campaign + KeepAlive loop.  
**Schwab:** Studio `temple_flow_wire` Act. Do not load that plist here. Do not create `config/LIVE_OK` on this laptop.

```sh
cd /Users/vaquez/temple-flow
export PYTHONPATH=src
STATE=/tmp/tf-kraken-run

python3 scripts/temple_flow_desk.py --state $STATE snapshot
python3 scripts/temple_flow_desk.py --state $STATE explain-cash
python3 scripts/temple_flow_desk.py --state $STATE attribution
python3 scripts/temple_flow_desk.py --state $STATE reconcile
python3 scripts/temple_flow_desk.py --state $STATE kraken-cycle          # evaluate
python3 scripts/temple_flow_desk.py --state $STATE flatten               # dry-run
# flatten --send cancels working stops then market-sells — human only

python3 -m unittest discover -s tests -q
```

Paper fixture: `--allow-paper-fixture` + examples/campaign_v2. Paper digest is not live authority.

KeepAlive: `launchctl print gui/$(id -u)/com.templetwo.temple-flow-kraken`
