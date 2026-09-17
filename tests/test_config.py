import json
import tempfile
import unittest
from pathlib import Path

from aci_inband.config import ConfigError, load_config, plan


def write(tmp_path: Path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def base():
    return {
        "apic_version": "5.2",
        "subnet_gateway": "10.20.30.1/24",
        "vlan": 301,
        "nodes": [{"node_id": 101, "address": "10.20.30.101/24"}],
    }


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_and_plan(self):
        config = load_config(write(self.tmp_path, base()))
        self.assertEqual(config.tenant, "mgmt")
        self.assertEqual(config.encap, "vlan-301")
        self.assertEqual(config.nodes[0].gateway, "10.20.30.1")
        self.assertEqual(
            plan(config)["node_addresses"][0]["target_dn"],
            "topology/pod-1/node-101",
        )

    def test_duplicate_ip_rejected(self):
        data = base()
        data["nodes"].append({"node_id": 102, "address": "10.20.30.101/24"})
        with self.assertRaisesRegex(ConfigError, "duplicate node IP"):
            load_config(write(self.tmp_path, data))

    def test_node_must_share_subnet(self):
        data = base()
        data["nodes"][0]["address"] = "10.20.31.101/24"
        with self.assertRaisesRegex(ConfigError, "must be in"):
            load_config(write(self.tmp_path, data))

    def test_l3out_requires_public_scope(self):
        data = base()
        data["l3outs"] = ["mgmt-l3out"]
        with self.assertRaisesRegex(ConfigError, "must include public"):
            load_config(write(self.tmp_path, data))


if __name__ == "__main__":
    unittest.main()
