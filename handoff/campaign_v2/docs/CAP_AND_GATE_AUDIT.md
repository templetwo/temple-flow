# Cap and gate audit — retain the purpose, replace the mechanism

**Evidence scope:** pinned repository documents, schemas, launcher, selected wire source and searches at main `a5aa41b337c5f7522770225fb9a74121a1150283`. Not an exhaustive local/runtime inspection. The local builder must expand this inventory across all scripts and effective configuration before cutover. Sources R1–R10 are in `SOURCES_AND_VERIFICATION.md`.

**Interpretation:** REMOVE means remove from the new campaign-operated path after migration, not edit the running legacy daemon now. CONFIGURE means the accepted campaign selects the value or policy. KEEP means retain the real constraint with an explicit implementation. REPLACE means preserve its intent through a better mechanism. A threshold has no authority merely because it appears in an example JSON file.

| ID | Existing rule/surface | v2 disposition | Replacement and verification |
|---|---|---|---|
| C01 | Exact human approval on every ordinary ticket; R1/R2 | REPLACE | Authenticated campaign GO + machine decision receipt. No human per-order round trip. |
| C02 | MV session arm/disarm, 16:00 expiry; R1/R3 | REPLACE | Persistent campaign authority; session eligibility per venue. Protection never expires at close. |
| C03 | Desk delegation in Sep 15 §§7–8; R2 | KEEP/GENERALIZE | Funds-beast operates accepted campaigns, not just MV; no repeated permission request for settled scope. |
| C04 | Hard 4 / soft 3 positions, removed by Sep 15 §9; R2/R5/R7 | REMOVE | No campaign-independent count gate. Explicitly null count in full-loss profile; exchange open-order limits remain. |
| C05 | Ordinary 18% position notional; R1/R5 | CONFIGURE | No arbitrary ceiling in full-loss profile beyond funded allocation and sizing policy. Optional in bounded-loss profile. |
| C06 | MV exemption to 18%; R1 | RETIRE SPECIAL CASE | A common explicit campaign policy replaces lane-name exceptions. |
| C07 | 35% outbox ticket ceiling/default; R6/R7 | REMOVE UNIVERSAL | Exact cash/reservation math catches fat-finger; optional campaign cap can be selected deliberately. |
| C08 | 2.5% stop-risk per trade; R1 | CONFIGURE | Not a universal constant. Full-loss mode explicitly disables this limit; size still comes from a documented algorithm. |
| C09 | 4.5% daily loss breaker; R1 | CONFIGURE | Disabled in full-loss mode; selected latch in bounded-loss mode with cash-flow-adjusted inputs. |
| C10 | 18% high-water drawdown breaker; R1 | CONFIGURE + CORRECT DATA | Disabled in full-loss mode; if selected, use durable high-water history, not today's equity copied to peak. |
| C11 | Human-only reset of financial latches; R1 | KEEP WHERE APPLICABLE | No reset work for disabled latches. A selected latch cannot be cleared by reboot, midnight or strategy rename. |
| C12 | ATR14 >1.8×60-day mean => half size/skip; R1/R8 | CONFIGURE | Strategy/portfolio volatility rule with explicit timeframe and historical definition; do not mechanically use equity daily gates for every crypto trade. |
| C13 | Hard stop on every live position; R1/R9 | KEEP PURPOSE / GENERALIZE | Qualified exit/protection policy, native where supported; no fixed stop distance, no guarantee of execution price. |
| C14 | No leverage beyond cash limits; R1 | KEEP | No borrowing, shorts, derivatives, auto-funding or overdraft in this build. Current funded equity, not gross margin buying power. |
| C15 | ETHA/IBIT literal live universe; R1/R7 | REPLACE | Campaign-approved eligibility policy and instrument registry; qualified in-scope names can be added by Funds-beast. |
| C16 | NVO/NOK protect-only status; R1/R3 | REPLACE ON ADOPTION | Existing holdings get explicit adoption/protect/exit disposition at GO. Do not immediately liquidate them just to simplify code. |
| C17 | GTC-only entry / no DAY; R1/R3 | REPLACE | Strategy- and venue-qualified time-in-force; use expiry appropriate to signal life. Unsupported combinations remain blocked. |
| C18 | Fixed cap price / no chase; R1/R8 | KEEP INTENT / RECOMPUTE | Enforce current price/impact/edge validity. A fresh independent strategy evaluation can produce a new cap inside the campaign; no human reapproval required. |
| C19 | No adds to an existing long (`already_long_no_add`); R7 | REPLACE | Aggregate position/lot risk and sell reservations. Permit qualified scale-in without treating every add as a new unlimited budget. |
| C20 | Per-symbol existing SELL blocks another bracket; R9 | REPLACE CAREFULLY | Quantity-aware inventory plus native OCO/OTO semantics. No oversell and no unqualified stop replacement. |
| C21 | Duplicate working entry guard; R7 | KEEP PURPOSE | Durable intent/client IDs, exclusive writer and reservation accounting; distinct qualified tranches are not mistaken for duplicates. |
| C22 | Manual promotion of plans with `--approve-plan`; R7/R8 | REPLACE | Plans feed registered strategies; active campaign consumes freshly valid machine intents directly. Legacy approvals stay historical. |
| C23 | Plan max age 24h, authorization until next close; R7 | SEPARATE | Campaign authority outlives individual signals. Signal TTL and quote freshness remain strategy-specific machine checks. |
| C24 | 900-second StartInterval / `--once`; R10 | REPLACE | Persistent event-driven daemon, supervisor restart only; no 15-minute decision scheduler. |
| C25 | History re-evaluation can delay protection; R7 | REPLACE | Async research/cache refresh separate from priority reconciliation and exit tasks; no blocking history/model call in send-critical loop. |
| C26 | WAIT vs terminal quarantine requires hand-moved files; R7 | REPLACE | Typed decline/health states; reevaluate new opportunities on recovery without resurrecting stale orders. No indefinite silent queue. |
| C27 | RTH-only cancellation + daily HTTP400 refusal memory; R9 | CAPABILITY-DRIVEN | Retain until native order status/session behavior is qualified. Use reason-specific retry and exchange state, not blind fast retries. |
| C28 | Cash/equity <=25% end-of-week and recycle clocks; R2 | REPLACE | Eligible-capital and stranded-opportunity diagnostics; no forced purchase or sale solely to pass a utilization quota. |
| C29 | Morning human approval window and weekly desk cadence; R2/R4 | REMOVE FROM EXECUTION | Briefs are observability. Execution/recycling are event-driven within market permissions. |
| C30 | Macro hold / nine-seat discussion; R2/R3/R4 | REPLACE | Optional predeclared event policies and asynchronous evidence. Missing conversation is not an implicit trade veto. |
| C31 | Two-digit ticket IDs, broker constant, open_positions max4; R5 | REPLACE | Versioned unified UUID-based contracts; historical tickets remain readable and never become live on import. |
| C32 | `LIVE_OK`, env flag, live launcher; R7/R10 | REPLACE AT CUTOVER | One credential-bound writer permission + accepted grant + fresh mechanical capability evidence; sample mode switch cannot arm. |
| C33 | Twelve Data evidence-only; R11 | KEEP | Evidence/research use only; native venue feeds for execution. Do not promote cached eyes data silently. |
| C34 | One-sell checks only in planner/outbox, not raw helper; R9 | FIX BOUNDARY | All credential-bearing submit paths require normalized intent/decision validation. Retire bypass scripts from live use. |
| C35 | Closed-market quotes / historical equity hints; R6/R7 | KEEP HONESTY | Exclude stale marks from spendability and realizable target decisions. Never use examples as account state. |
| C36 | Fixed UTC-4 fallback if zoneinfo fails; R7 | REPLACE | Valid IANA timezone/calendar required for equities; unknown clock/calendar blocks affected entries instead of guessing DST. |
| C37 | Minimum size/tick, broker settlement and exchange rate limits | KEEP EXTERNAL | Dynamic capability snapshots; not removable project policy. Source/time each actual restriction. |
| C38 | v1 CV off-hours-only entry default / old inherited risk percentages; legacy v1 | SUPERSEDE | Both lanes use campaigns; Kraken eligible continuously. Full-loss policy is explicit and independent of the old RTH session. |
| C39 | “Stop at zero” as equality test; prior discussion | CORRECT | Total-loss consent plus tradable exhaustion/residual state; preserve dust truthfully, never force a zero balance. |
| C40 | Optimize only probability of hitting a target; prior discussion | CORRECT | Goal is objective/termination metadata, not a reward for taking ruinous bets or escalating after losses. |

## Required local-audit completion

Search all code, config loaders, schemas, tests, shell wrappers, launch definitions and direct-send helpers. Record aliases (for example max_opens/open_positions/max_positions) and computed limits, not just exact strings. Identify precedence and whether a value is actually read on the current live path. Inspect defaults, environment overrides, command flags and generated files. Follow new policy fields end-to-end to the lowest credential-bearing boundary.

Use a generated policy table and contract tests to prevent README, constitution, sample settings and runtime from disagreeing. Preserve historical files under an explicit version; do not rewrite them and pretend they always permitted campaigns. An unknown policy key fails compilation. Disabled is not missing; disabled includes a reason and an accepted grant.

**Causality caution:** the reviewed source says the default four-name gate can pass with the two-entry-name universe because earlier checks often constrain the book to at most three relevant names. Do not present C04 as the proven explanation for Anthony's full $432 idle-cash report. The new instrumentation must identify which exact state/guard delayed each actual signal. [R7]
