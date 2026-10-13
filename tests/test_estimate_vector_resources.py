from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "estimate_vector_resources.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "estimate_vector_resources", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EstimateVectorResourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def parse(self, *args: str):
        return self.module.parser().parse_args(args)

    def test_final_nodes_use_largest_constraint(self) -> None:
        result = self.module.estimate(
            self.parse(
                "--vector-count",
                "10000000",
                "--dimension",
                "768",
                "--non-vector-gib",
                "100",
                "--replicas",
                "1",
                "--instance-memory-gib",
                "64",
                "--instance-vcpu",
                "8",
                "--ebs-gib-per-node",
                "100",
                "--ha-minimum-nodes",
                "3",
            )
        )
        self.assertEqual(result.primary_shards, 4)
        self.assertEqual(result.active_shards, 8)
        self.assertEqual(result.required_vcpu, 8)
        self.assertEqual(result.nodes_by_cpu, 1)
        self.assertEqual(result.nodes_by_storage, 4)
        self.assertEqual(result.final_data_nodes, 4)
        self.assertEqual(result.winning_constraints, ["storage"])

    def test_cpu_can_be_winning_constraint(self) -> None:
        result = self.module.estimate(
            self.parse(
                "--vector-count",
                "1000000",
                "--dimension",
                "384",
                "--vector-disk-gib",
                "400",
                "--storage-overhead-factor",
                "1",
                "--storage-headroom-factor",
                "1",
                "--target-primary-shard-gib",
                "25",
                "--replicas",
                "1",
                "--instance-memory-gib",
                "64",
                "--instance-vcpu",
                "4",
                "--ebs-gib-per-node",
                "1000",
            )
        )
        self.assertEqual(result.active_shards, 32)
        self.assertEqual(result.required_vcpu, 32)
        self.assertEqual(result.nodes_by_cpu, 8)
        self.assertEqual(result.final_data_nodes, 8)
        self.assertEqual(result.winning_constraints, ["cpu"])

    def test_memory_compression_does_not_change_disk_size(self) -> None:
        base = self.module.estimate(
            self.parse("--vector-count", "1000000", "--dimension", "768")
        )
        compressed = self.module.estimate(
            self.parse(
                "--vector-count",
                "1000000",
                "--dimension",
                "768",
                "--memory-compression",
                "4",
            )
        )
        self.assertEqual(
            base.primary_vector_disk_gib, compressed.primary_vector_disk_gib
        )
        self.assertLess(
            compressed.total_knn_memory_gib, base.total_knn_memory_gib
        )

    def test_measured_primary_store_bypasses_overhead_estimate(self) -> None:
        result = self.module.estimate(
            self.parse(
                "--vector-count",
                "1000000",
                "--dimension",
                "768",
                "--non-vector-gib",
                "100",
                "--storage-overhead-factor",
                "2",
                "--primary-index-gib",
                "150",
            )
        )
        self.assertEqual(result.primary_index_gib, 150)
        self.assertEqual(result.primary_index_source, "measured_primary_store")
        self.assertEqual(result.primary_shards, 3)

    def test_json_cli_output(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--vector-count",
                "1000000",
                "--dimension",
                "768",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["primary_shards"], 1)
        self.assertIsNone(payload["final_data_nodes"])
        self.assertIn("non-vector data is zero", payload["warnings"][0])


if __name__ == "__main__":
    unittest.main()
