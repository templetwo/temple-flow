# Contract scope and versioning

JSON schemas are closed Draft 2020-12 documents. Run the semantic checks as well as shape validation. Monetary fields are decimal strings, not binary floats. Quantities are rounded against instrument metadata at runtime, not fixed cents or fixed equity shares in these schemas.

`campaign.v2` is an immutable proposed/prepared definition. Runtime lifecycle (RUNNING, TARGET_EXITING, STOPPED, etc.) is a separate durable event stream. A grant references the exact prepared revision and frozen scope. Definition status is not proof of authority. The activation fields identify intended receipts only; a production service must look up their trusted records, principals, revocations and deployment ownership rather than trusting a JSON file. The offline tools in this bundle do not issue grants or connect to brokers.

A `full_loss_research` definition explicitly disables optional percentage/name-count checks and accepts allocation loss. `bounded_loss` must choose at least one selected loss boundary; a limit cannot silently disappear. No profile authorizes borrowing. Live draft has unresolved balances, registered strategy/sizing/exit/service-budget references and no target inferred from the earlier illustration. Prepare resolves those facts in one preview.

`order_intent.v2` covers limit-priced entry or exit decisions. It does not claim to cover every broker order type. The builder must add separately versioned cancel, amend, protection and grant contracts based on the adapter protocol, with ownership and generation checks. A positive-entry-edge condition never blocks required protective action.

`decision.v2` records an entry decision and its resource/evidence basis; PASS is not authentication. The durable writer resolves its exact relationship to the reservation, intent, policy and account state before sending. Fake policy digests/IDs in the paper fixtures are deliberately not genuine receipts.

All examples are unarmed. Paper fixture values and the bounded-loss fixture's 4% value are test inputs, not proposed personal investment settings. The file schemas are build starting points; a complete execution runtime, authenticated control plane and actual venue tests remain work for Grok.
