# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""SortCert: deterministic sorted-list certificate primitive.

One thing: given a list of integers, certify whether it is sorted
in non-decreasing order.

The leader and every validator independently recompute, for each
adjacent pair, values[i] <= values[i + 1]. The full per-pair boolean
vector is the decision-bearing payload: leader and validator vectors
must agree element-wise, exactly, with zero tolerance — no aggregates,
no scores, no thresholds. Any single pair that differs flips the
verdict.

The caller also submits a claimed per-pair vector and a claimed
verdict. The equivalence gate compares both against the recomputed
values, element by element, with zero tolerance:

  - claimed_pair_results != recomputed vector -> UserError PAIR_MISMATCH
  - claimed_verdict != recomputed verdict     -> UserError VERDICT_MISMATCH

A failed claim creates NO record, so the same case_id can be retried
with the correct claim.

Verdicts (fixed enumeration, exactly two):
  - SORTED: every adjacent pair is non-decreasing.
  - UNSORTED: at least one adjacent pair is inverted.
The witness for UNSORTED is the first inverted pair: its pair index
(which equals i), the index i, and the two values values[i] and
values[i + 1]. The witness is part of the stored record, never
overwritten.

State machine: a case is DECIDED the moment it is created, and it is
terminal — there is no update method, a second create_case with the
same case_id always fails, and the verdict can never change.

No LLM is used: this is pure deterministic integer comparison. The
consequence is informational only: no GEN moves, no money, nothing
is payable. Synthetic demo data is sufficient.
"""

import json

from genlayer import *

PROTOCOL = "sortcert-1"
MIN_VALUES = 2
MAX_VALUES = 16
VALUE_MIN = -1000000
VALUE_MAX = 1000000
MAX_CASE_ID = 64
VERDICT_SORTED = "SORTED"
VERDICT_UNSORTED = "UNSORTED"


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def need(ok, code):
    if not ok:
        raise gl.vm.UserError("EXPECTED: " + code)


def unique_pairs(pairs):
    d = {}
    for key, value in pairs:
        need(key not in d, "DUPLICATE_JSON_KEY")
        d[key] = value
    return d


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs) if isinstance(raw, str) else raw


def compute_pair_results(values):
    """Pure function: the full per-pair boolean vector.

    pair_results[i] is True exactly when values[i] <= values[i + 1].
    This vector is the whole decision: the verdict is SORTED iff
    every entry is True.
    """
    return [values[i] <= values[i + 1] for i in range(len(values) - 1)]


class SortCert(gl.Contract):
    cases: TreeMap[str, str]
    total_cases: u32
    sorted_cases: u32
    unsorted_cases: u32

    def __init__(self):
        self.total_cases = u32(0)
        self.sorted_cases = u32(0)
        self.unsorted_cases = u32(0)

    @gl.public.view
    def get_protocol(self) -> str:
        return pack({
            "protocol": PROTOCOL,
            "min_values": MIN_VALUES,
            "max_values": MAX_VALUES,
            "value_min": VALUE_MIN,
            "value_max": VALUE_MAX,
            "verdicts": [VERDICT_SORTED, VERDICT_UNSORTED],
            "states": ["DECIDED"],
        })

    @gl.public.view
    def get_case(self, case_id: str) -> str:
        return self.cases.get(case_id, "")

    @gl.public.view
    def get_stats(self) -> str:
        return pack({
            "total_cases": int(self.total_cases),
            "sorted_cases": int(self.sorted_cases),
            "unsorted_cases": int(self.unsorted_cases),
        })

    @gl.public.write
    def create_case(self, case_id: str, values_json: str, claimed_pair_results_json: str, claimed_verdict: str) -> str:
        need(type(case_id) is str and 1 <= len(case_id) <= MAX_CASE_ID, "CASE_ID_LENGTH")
        need(not self.cases.get(case_id, ""), "ALREADY_EXISTS")
        need(len(values_json) <= 500 and len(claimed_pair_results_json) <= 500, "INPUT_BOUND")
        values = parse(values_json)
        claimed_pair_results = parse(claimed_pair_results_json)
        need(type(values) is list and MIN_VALUES <= len(values) <= MAX_VALUES, "VALUE_COUNT_2_16")
        need(all(type(x) is int and not isinstance(x, bool) for x in values), "VALUE_FORMAT")
        need(all(VALUE_MIN <= x <= VALUE_MAX for x in values), "VALUE_RANGE")
        need(type(claimed_pair_results) is list and len(claimed_pair_results) == len(values) - 1, "CLAIMED_RESULTS_LENGTH")
        need(all(type(x) is bool for x in claimed_pair_results), "CLAIMED_RESULTS_FORMAT")
        need(type(claimed_verdict) is str, "CLAIMED_VERDICT_FORMAT")

        pair_results = compute_pair_results(values)
        verdict = VERDICT_SORTED if all(pair_results) else VERDICT_UNSORTED
        # Equivalence gate: the claim must match the recomputation
        # element by element, zero tolerance. A mismatch fails the
        # whole call and creates no record.
        need(claimed_pair_results == pair_results, "PAIR_MISMATCH")
        need(claimed_verdict == verdict, "VERDICT_MISMATCH")

        witness = None
        first_inversion_pair_index = -1
        if verdict == VERDICT_UNSORTED:
            first_inversion_pair_index = pair_results.index(False)
            i = first_inversion_pair_index
            witness = {
                "pair_index": i,
                "i": i,
                "left": values[i],
                "right": values[i + 1],
            }

        case = {
            "id": case_id,
            "values": values,
            "claimed_pair_results": claimed_pair_results,
            "claimed_verdict": claimed_verdict,
            "pair_results": pair_results,
            "verdict": verdict,
            "first_inversion_pair_index": first_inversion_pair_index,
            "witness": witness,
            "state": "DECIDED",
        }
        self.cases[case_id] = pack(case)
        self.total_cases = u32(int(self.total_cases) + 1)
        if verdict == VERDICT_SORTED:
            self.sorted_cases = u32(int(self.sorted_cases) + 1)
        else:
            self.unsorted_cases = u32(int(self.unsorted_cases) + 1)
        return pack({
            "id": case_id,
            "verdict": verdict,
            "pair_results": pair_results,
            "first_inversion_pair_index": first_inversion_pair_index,
            "witness": witness,
            "state": "DECIDED",
        })
