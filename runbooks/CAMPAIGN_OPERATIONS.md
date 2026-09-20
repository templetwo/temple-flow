# Campaign operations (v2 paper)

The live Schwab Act loop is still `scripts/temple_flow_wire.py` under Studio launchd.
This runbook is the **isolated paper desk**. Do not point `--state` at the Studio
repo root. Do not create `config/LIVE_OK`. Do not load launchd from this path.

```sh
cd /Users/vaquez/temple-flow
PYTHONPATH=src python3 scripts/temple_flow_desk.py --state /tmp/tf-paper prepare \
  --campaign examples/campaign_v2/campaign.paper_100_to_200.json
PYTHONPATH=src python3 scripts/temple_flow_desk.py --state /tmp/tf-paper go \
  --campaign-id TF-CAMPAIGN-PAPER-DEMO --revision 1 --digest <digest from prepare>
PYTHONPATH=src python3 scripts/temple_flow_desk.py --state /tmp/tf-paper paper-cycle
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Preview: `docs/campaign_v2/CAMPAIGN_PREVIEW_GO.md`. Paper GO is not a live grant.
Existing stops stay on the broker until a separately authorized cutover (WP7).
