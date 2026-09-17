import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "postman" / "ACI-5.2-Inband-Management.postman_collection.json"
ENVIRONMENT = ROOT / "postman" / "ACI-5.2-Inband-Management.postman_environment.json"


def request_names(items):
    """Yield request names recursively from Postman's nested folder structure."""
    for item in items:
        if "request" in item:
            yield item["name"]
        yield from request_names(item.get("item", []))


class PostmanArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # json.loads is also a strict syntax check for both importable artifacts.
        cls.collection = json.loads(COLLECTION.read_text(encoding="utf-8"))
        cls.environment = json.loads(ENVIRONMENT.read_text(encoding="utf-8"))

    def test_collection_schema_and_core_requests(self):
        self.assertEqual(
            self.collection["info"]["schema"],
            "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        )
        names = set(request_names(self.collection["item"]))
        self.assertTrue(
            {
                "Login to APIC",
                "Create or update in-band management objects",
                "Create leaf access port policy group",
                "Add selectors to existing leaf interface profiles",
                "Read in-band EPG and all children",
            }.issubset(names)
        )

    def test_example_environment_contains_no_password(self):
        values = {item["key"]: item["value"] for item in self.environment["values"]}
        self.assertEqual(values["password"], "")
        self.assertEqual(values["apic_token"], "")
        self.assertEqual(values["configure_access_policy"], "false")

    def test_json_array_variables_are_valid_arrays(self):
        values = {item["key"]: item["value"] for item in self.environment["values"]}
        for name in (
            "nodes_json",
            "l3outs_json",
            "provided_contracts_json",
            "consumed_contracts_json",
            "access_interfaces_json",
        ):
            self.assertIsInstance(json.loads(values[name]), list)


if __name__ == "__main__":
    unittest.main()
