import unittest

from packaging.version import Version

from workflow_cockpit.engine.interactive_contract import (
    PromptContract,
    resolve_contract,
    verified_releases,
)


class ResolveContractTests(unittest.TestCase):
    def test_released_version_resolves_by_exact_identity(self):
        contract = resolve_contract(Version("1.0.6"))
        self.assertIsNotNone(contract)
        self.assertEqual(contract.release, (1, 0, 6))
        self.assertEqual(contract.strategy, "index")
        self.assertEqual(contract.terminator, b"\n")

    def test_dev_version_resolves_by_exact_identity(self):
        contract = resolve_contract("1.0.6.dev0")
        self.assertIsNotNone(contract)
        self.assertEqual(contract.release, (1, 0, 6))

    def test_unverified_versions_are_none_not_a_guess(self):
        for version in ("1.0.5", "2.0.0", "1.0.6.dev1", "1.0.6.post1", "1.0.6+local", "not-a-version"):
            with self.subTest(version=version):
                self.assertIsNone(resolve_contract(version))
        self.assertNotIn(Version("9.9.9"), verified_releases())


class MapChoiceTests(unittest.TestCase):
    def contract(self, strategy="index") -> PromptContract:
        return PromptContract(release=(1, 0, 6), readiness="verified", strategy=strategy)

    def test_index_mapping_writes_one_based_position(self):
        data, reason = self.contract().map_choice("reject", ("approve", "reject"))
        self.assertIsNone(reason)
        self.assertEqual(data, b"2\n")

    def test_value_mapping_writes_choice_and_newline(self):
        data, reason = self.contract("value").map_choice("approve", ("approve", "reject"))
        self.assertIsNone(reason)
        self.assertEqual(data, b"approve\n")

    def test_value_mapping_rejects_control_characters(self):
        data, reason = self.contract("value").map_choice("approve\nrun", ("approve\nrun",))
        self.assertIsNone(data)
        self.assertIn("control", reason)

    def test_case_insensitive_collision_is_unsupported(self):
        data, reason = self.contract().map_choice("Approve", ("Approve", "approve"))
        self.assertIsNone(data)
        self.assertIn("ambiguous", reason)

    def test_unknown_choice_is_unsupported(self):
        data, reason = self.contract().map_choice("maybe", ("approve", "reject"))
        self.assertIsNone(data)
        self.assertIn("not one of", reason)

    def test_empty_options_are_unsupported(self):
        data, reason = self.contract().map_choice("approve", ())
        self.assertIsNone(data)
        self.assertIn("no options", reason)

    def test_unknown_strategy_is_unsupported(self):
        data, reason = self.contract("free-text").map_choice("approve", ("approve",))
        self.assertIsNone(data)
        self.assertIn("not supported", reason)


if __name__ == "__main__":
    unittest.main()
