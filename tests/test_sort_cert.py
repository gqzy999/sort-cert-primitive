"""Local mock tests for SortCert. NOT chain consensus evidence.

The real contract source (contracts/sort_cert.py) is imported with
a stubbed `genlayer` module: the host fakes the VM so the contract's
deterministic logic can be exercised locally. Passing here proves the
pair recomputation, the verdicts, the witness, the equivalence gate,
and the immutability guards in this file; on-chain proof comes only
from the FINALIZED transactions in evidence.json.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


class Map(dict):
    @classmethod
    def __class_getitem__(cls, value):
        return cls


class _Write:
    def __call__(self, f):
        return f

    def payable(self, f):
        return f


identity = lambda f: f


class UserError(Exception):
    pass


host = types.SimpleNamespace(
    Contract=object,
    public=types.SimpleNamespace(view=identity, write=_Write()),
    message=types.SimpleNamespace(sender_address="0x" + "1" * 40, value=0),
    evm=types.SimpleNamespace(contract_interface=identity),
    vm=types.SimpleNamespace(UserError=UserError, Return=object),
    nondet=types.SimpleNamespace(),
)
sdk = types.ModuleType("genlayer")
sdk.gl, sdk.TreeMap, sdk.u32, sdk.u256 = host, Map, int, int
sdk.Address = lambda a: a
sys.modules["genlayer"] = sdk

spec = importlib.util.spec_from_file_location(
    "sort_cert", Path(__file__).parents[1] / "contracts" / "sort_cert.py"
)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def expect_error(fn, code):
    with unittest.TestCase().assertRaises(UserError) as ctx:
        fn()
    assert code in str(ctx.exception), f"expected {code}, got {ctx.exception}"


class CertTests(unittest.TestCase):
    def setUp(self):
        self.c = r.SortCert()
        self.c.cases = Map()
        self.c.total_cases = 0
        self.c.sorted_cases = 0
        self.c.unsorted_cases = 0

    def create(self, case_id, values, claimed, verdict):
        return self.c.create_case(
            case_id,
            json.dumps(values),
            json.dumps(claimed),
            verdict,
        )

    def test_protocol(self):
        p = json.loads(self.c.get_protocol())
        self.assertEqual(p["protocol"], "sortcert-1")
        self.assertEqual(p["verdicts"], ["SORTED", "UNSORTED"])
        self.assertEqual(p["states"], ["DECIDED"])
        self.assertEqual(p["min_values"], 2)
        self.assertEqual(p["max_values"], 16)
        self.assertEqual(p["value_min"], -1000000)
        self.assertEqual(p["value_max"], 1000000)

    def test_compute_pair_results(self):
        self.assertEqual(r.compute_pair_results([1, 2, 2, 5]), [True, True, True])
        self.assertEqual(r.compute_pair_results([3, 1, 2]), [False, True])
        self.assertEqual(r.compute_pair_results([5, 4, 3, 2, 1]), [False, False, False, False])
        self.assertEqual(r.compute_pair_results([-5, 0, 0, 7]), [True, True, True])
        # Equal neighbours are non-decreasing, not an inversion.
        self.assertEqual(r.compute_pair_results([2, 2]), [True])

    def test_sorted_list_is_sorted(self):
        out = json.loads(self.create(
            "sorted-list", [1, 2, 2, 5], [True, True, True], "SORTED",
        ))
        self.assertEqual(out["verdict"], "SORTED")
        self.assertEqual(out["pair_results"], [True, True, True])
        self.assertEqual(out["first_inversion_pair_index"], -1)
        self.assertIsNone(out["witness"])
        self.assertEqual(out["state"], "DECIDED")
        stored = json.loads(self.c.get_case("sorted-list"))
        self.assertEqual(stored["verdict"], "SORTED")
        self.assertEqual(stored["values"], [1, 2, 2, 5])
        self.assertEqual(stored["claimed_pair_results"], [True, True, True])
        self.assertEqual(stored["claimed_verdict"], "SORTED")
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats, {"total_cases": 1, "sorted_cases": 1, "unsorted_cases": 0})

    def test_unsorted_list_has_first_inversion_witness(self):
        out = json.loads(self.create(
            "unsorted-list", [3, 1, 2], [False, True], "UNSORTED",
        ))
        self.assertEqual(out["verdict"], "UNSORTED")
        self.assertEqual(out["pair_results"], [False, True])
        self.assertEqual(out["first_inversion_pair_index"], 0)
        self.assertEqual(out["witness"], {
            "pair_index": 0, "i": 0, "left": 3, "right": 1,
        })
        stored = json.loads(self.c.get_case("unsorted-list"))
        self.assertEqual(stored["witness"]["left"], 3)
        self.assertEqual(stored["witness"]["right"], 1)
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats, {"total_cases": 1, "sorted_cases": 0, "unsorted_cases": 1})

    def test_first_inversion_wins_when_several_invert(self):
        # [5, 4, 3]: both pairs invert; the witness is pair 0 (5 > 4).
        out = json.loads(self.create(
            "two-inversions", [5, 4, 3], [False, False], "UNSORTED",
        ))
        self.assertEqual(out["verdict"], "UNSORTED")
        self.assertEqual(out["first_inversion_pair_index"], 0)
        self.assertEqual(out["witness"], {
            "pair_index": 0, "i": 0, "left": 5, "right": 4,
        })
        # [1, 3, 2, 0]: first inversion is pair 1 (3 > 2), not pair 2.
        out2 = json.loads(self.create(
            "later-inversion", [1, 3, 2, 0], [True, False, False], "UNSORTED",
        ))
        self.assertEqual(out2["first_inversion_pair_index"], 1)
        self.assertEqual(out2["witness"], {
            "pair_index": 1, "i": 1, "left": 3, "right": 2,
        })

    def test_bad_claimed_vector_is_rejected_and_creates_no_record(self):
        expect_error(
            lambda: self.create(
                "bad-claim", [1, 2, 2, 5], [True, True, False], "SORTED",
            ),
            "PAIR_MISMATCH",
        )
        self.assertEqual(self.c.get_case("bad-claim"), "")
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats["total_cases"], 0)
        # Same case_id can be retried with the correct claim.
        out = json.loads(self.create(
            "bad-claim", [1, 2, 2, 5], [True, True, True], "SORTED",
        ))
        self.assertEqual(out["verdict"], "SORTED")

    def test_bad_claimed_verdict_is_rejected(self):
        expect_error(
            lambda: self.create(
                "bad-verdict", [3, 1, 2], [False, True], "SORTED",
            ),
            "VERDICT_MISMATCH",
        )
        self.assertEqual(self.c.get_case("bad-verdict"), "")
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats["total_cases"], 0)

    def test_case_is_immutable(self):
        self.create("once", [1, 2, 2, 5], [True, True, True], "SORTED")
        expect_error(
            lambda: self.create("once", [3, 1, 2], [False, True], "UNSORTED"),
            "ALREADY_EXISTS",
        )
        stored = json.loads(self.c.get_case("once"))
        self.assertEqual(stored["verdict"], "SORTED")
        self.assertEqual(stored["values"], [1, 2, 2, 5])

    def test_input_validation(self):
        expect_error(lambda: self.create("", [1, 2], [True], "SORTED"), "CASE_ID_LENGTH")
        expect_error(lambda: self.create("one-value", [1], [], "SORTED"), "VALUE_COUNT_2_16")
        expect_error(lambda: self.create("too-many", list(range(17)), [True] * 16, "SORTED"), "VALUE_COUNT_2_16")
        expect_error(lambda: self.create("too-big", [1, 1000001], [True], "SORTED"), "VALUE_RANGE")
        expect_error(lambda: self.create("too-small", [-1000001, 1], [True], "SORTED"), "VALUE_RANGE")
        # Boundary values themselves are valid: [-1000000, 1000000] is SORTED.
        out = json.loads(self.create("boundary", [-1000000, 1000000], [True], "SORTED"))
        self.assertEqual(out["verdict"], "SORTED")
        expect_error(lambda: self.create("bad-type", [1, "2"], [True], "SORTED"), "VALUE_FORMAT")
        expect_error(lambda: self.create("bool-value", [1, True], [True], "SORTED"), "VALUE_FORMAT")
        expect_error(lambda: self.create("short-claim", [1, 2, 3], [True], "SORTED"), "CLAIMED_RESULTS_LENGTH")
        expect_error(lambda: self.create("nonbool-claim", [1, 2], [1], "SORTED"), "CLAIMED_RESULTS_FORMAT")
        self.assertEqual(self.c.get_case("missing"), "")
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats["total_cases"], 1)  # only the boundary case succeeded


if __name__ == "__main__":
    unittest.main()
