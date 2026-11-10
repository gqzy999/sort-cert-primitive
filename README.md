# SortCert — deterministic sorted-list certificate primitive

排序证书原语：给定一个整数列表，验证它是否已按非递减顺序排序。

SortCert is a deterministic sorted-list certificate primitive: given a list of integers, it decides whether the list is sorted in non-decreasing order.

- Network: Stable Studionet, Chain ID 61999, RPC https://studio.genlayer.com/api
- Contract: `0xD084BF64ccdf9bB347d0F6ffB20641A2095b25a0`
- Explorer: https://explorer-studio.genlayer.com/address/0xD084BF64ccdf9bB347d0F6ffB20641A2095b25a0
- Source: `contracts/sort_cert.py`
- Source SHA-256: `ff425edcb95aafb012c4a335f3711fa23c6740114bbb2c6ad0d68143df0efb21`
- Deployed code matches the source byte for byte (checked with `gen_getContractCode`).

## Mechanism / 机制

One thing, one fixed enumeration, exact equality on the full vector.

`create_case(case_id, values_json, claimed_pair_results_json, claimed_verdict)` takes a case id, a list of integers, a claimed per-pair boolean vector, and a claimed verdict. The leader and every validator independently recompute, for each adjacent pair, `values[i] <= values[i + 1]`. The full per-pair boolean vector is the decision-bearing payload: leader and validator vectors must agree element-wise, exactly, with zero tolerance — no aggregates, no scores, no thresholds. Any single pair that differs flips the verdict.

Equivalence gate (the hard bar): the claimed vector must equal the recomputed vector element by element, zero tolerance (`PAIR_MISMATCH` otherwise), and the claimed verdict must equal the recomputed verdict (`VERDICT_MISMATCH` otherwise). A failed claim creates NO record, so the same case_id can be retried with the correct claim.

Verdicts (fixed enumeration, exactly two):

- `SORTED` — every adjacent pair is non-decreasing (equal neighbours count as sorted).
- `UNSORTED` — at least one adjacent pair is inverted. The witness is the first inverted pair: `{ pair_index, i, left, right }` where `left = values[i]`, `right = values[i + 1]`, and `pair_index = i`. The witness is part of the stored record.

No LLM is used: this is pure deterministic integer comparison. The consequence is informational only — `create_case` is not payable, no GEN moves, no money changes hands.

## State machine / 状态机

```
create_case --> DECIDED (terminal)
```

- A case is `DECIDED` the moment it is created. There is no update method: a second `create_case` with the same `case_id` fails with `ALREADY_EXISTS`, and the stored verdict can never change.
- Input guards: 2–16 integers per list, each in the range −1,000,000 to 1,000,000; claimed vector must be booleans parallel to the adjacent pairs (length = values − 1).

## How to call / 调用方法

All on-chain values are English. The list arguments are JSON strings.

```js
// 1. Good case: sorted list [1,2,2,5].
//    -> SORTED, pair_results [true, true, true], witness null
create_case(
  "sorted-list",
  JSON.stringify([1, 2, 2, 5]),
  JSON.stringify([true, true, true]),
  "SORTED",
);

// 2. Bad claim: same list, but claimed [true, true, false].
//    -> on-chain ERROR PAIR_MISMATCH, no record created.
create_case(
  "bad-claim-list",
  JSON.stringify([1, 2, 2, 5]),
  JSON.stringify([true, true, false]),
  "SORTED",
);

// 3. Unsorted: list [3,1,2].
//    -> UNSORTED, pair_results [false, true],
//       witness { pair_index: 0, i: 0, left: 3, right: 1 }
create_case(
  "unsorted-list",
  JSON.stringify([3, 1, 2]),
  JSON.stringify([false, true]),
  "UNSORTED",
);
```

Reads:

```js
get_protocol(); // protocol, bounds, verdicts, states
get_case("sorted-list"); // id, values, claimed vector/verdict, pair_results, verdict, witness, state
get_stats(); // total_cases, sorted_cases, unsorted_cases
```

## Evidence / 证据

All transactions FINALIZED with MAJORITY_AGREE consensus. Full machine-readable evidence: [`evidence.json`](evidence.json). Deployment record: [`deployment.json`](deployment.json).

| Case | Transaction | Result |
| --- | --- | --- |
| Deploy | `0x75436b245294423f1999909f41ba8075aa6f5def7ef6090a2496db9c3a72b1b3` | FINALIZED, contract `0xD084BF64ccdf9bB347d0F6ffB20641A2095b25a0` |
| GOOD sorted `[1,2,2,5]` | `0x9bb523037f2fcfd446e0312b2d57b2d6be5bbf366455a2c49d367e5fa9eb72bd` | FINALIZED / SUCCESS — `SORTED`, pair_results `[true, true, true]`, witness null |
| BAD claim `[true,true,false]` | `0xa4a58c14223ce42247c44395bcd2a9c66ba288f982a45533fd5c41528bc3e7fc` | FINALIZED / ERROR `PAIR_MISMATCH` — no record created |
| GOOD unsorted `[3,1,2]` | `0xab56caaee6aa046f5afc378bb17d34a128b46f334629fe2960bfb99e06a3000a` | FINALIZED / SUCCESS — `UNSORTED`, pair_results `[false, true]`, witness pair 0 (3 > 1) |

Final read-backs: `get_stats()` → total 2, sorted 1, unsorted 1. All cases re-read live and match `evidence.json` exactly (`npm run verify`).

## Reuse / 复用价值

Any checker that needs a trustworthy sorted-list certificate can reuse this primitive: submit a list once, and anyone can read back the verdict, the full per-pair vector, and the first inverted pair as witness. The same contract also serves as the deterministic core for ordering checks in sorting, ranking, and data-pipeline validation in larger protocols.

## Tests / 测试

`tests/test_sort_cert.py` runs the real contract source locally with a stubbed host module (local mock only — not chain consensus evidence). It covers the sorted list, the unsorted list with its witness, first-inversion selection, the equivalence gate (bad vector and bad verdict), immutability, and input validation:

```bash
npm test   # python3 tests/test_sort_cert.py — 9 tests
```

Reproduce the on-chain flow and the independent re-check:

```bash
npm run deploy   # ephemeral deployer key; writes deployment.json
npm run flow     # evidence flow; writes evidence.json
npm run verify   # re-reads live state and compares with evidence.json
```

## Limits / 已知限制

- Lists are small by design: 2–16 integers per case, each in the range −1,000,000 to 1,000,000.
- The list is supplied by the caller; the contract has no independent anchor for where the list came from — it certifies that the supplied list is sorted, not that the list is the real data from any external source.
- The verdict is informational only: no GEN moves and no downstream consequence is enforced on-chain.
- Cases are immutable once created: a wrong submission cannot be corrected, only superseded by a new case id.
