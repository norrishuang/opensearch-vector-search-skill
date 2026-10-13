#!/usr/bin/env python3
"""Estimate OpenSearch vector resources from storage, shards, CPU, and KNN memory."""

from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import asdict, dataclass


GIB = 1024**3


@dataclass(frozen=True)
class Candidate:
    instance_type: str
    memory_gib: float
    vcpu: float
    ebs_gib_per_node: float
    monthly_instance_price: float


@dataclass(frozen=True)
class Estimate:
    primary_vector_disk_gib: float
    primary_non_vector_gib: float
    primary_index_gib: float
    primary_index_source: str
    total_provisioned_storage_gib: float
    primary_shards: int
    active_shards: int
    required_vcpu: int
    total_knn_memory_gib: float
    knn_memory_available_per_node_gib: float | None
    nodes_by_memory: int | None
    nodes_by_cpu: int | None
    nodes_by_storage: int | None
    ha_minimum_nodes: int
    final_data_nodes: int | None
    winning_constraints: list[str]
    ebs_gib_per_final_node: float | None
    warnings: list[str]


def positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def non_negative(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def candidate(value: str) -> Candidate:
    parts = value.split(":")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "candidate must be INSTANCE:MEMORY_GIB:VCPU:EBS_GIB:MONTHLY_PRICE"
        )
    name, memory, vcpu, ebs, price = parts
    if not name:
        raise argparse.ArgumentTypeError("candidate instance type cannot be empty")
    try:
        parsed = Candidate(
            instance_type=name,
            memory_gib=float(memory),
            vcpu=float(vcpu),
            ebs_gib_per_node=float(ebs),
            monthly_instance_price=float(price),
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "candidate resource and price fields must be numbers"
        ) from exc
    if min(
        parsed.memory_gib,
        parsed.vcpu,
        parsed.ebs_gib_per_node,
        parsed.monthly_instance_price,
    ) <= 0:
        raise argparse.ArgumentTypeError("candidate values must be greater than zero")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Estimate OpenSearch vector resources using independent storage/shard, "
            "vCPU, KNN-memory, and availability constraints."
        )
    )
    result.add_argument("--vector-count", type=int, required=True)
    result.add_argument("--dimension", type=int, required=True)
    result.add_argument("--bytes-per-dimension", type=positive, default=4.0)
    result.add_argument(
        "--memory-compression",
        type=positive,
        default=1.0,
        help="Vector payload compression in KNN memory (default: 1)",
    )
    result.add_argument(
        "--vector-disk-compression",
        type=positive,
        default=1.0,
        help="Persisted vector compression, independent of memory compression (default: 1)",
    )
    result.add_argument(
        "--vector-disk-gib",
        type=positive,
        help="Measured primary vector disk size; overrides the vector formula",
    )
    result.add_argument(
        "--primary-index-gib",
        type=positive,
        help="Measured pri.store.size; overrides component and overhead estimation",
    )
    result.add_argument("--non-vector-gib", type=non_negative, default=0.0)
    result.add_argument("--storage-overhead-factor", type=positive, default=1.2)
    result.add_argument("--storage-headroom-factor", type=positive, default=1.2)
    result.add_argument("--target-primary-shard-gib", type=positive, default=50.0)
    result.add_argument("--replicas", type=int, default=1)
    result.add_argument("--active-shards-per-vcpu", type=positive, default=1.0)
    result.add_argument("--hnsw-m", type=int, default=16)
    result.add_argument("--instance-memory-gib", type=positive)
    result.add_argument("--instance-vcpu", type=positive)
    result.add_argument("--ebs-gib-per-node", type=positive)
    result.add_argument("--ha-minimum-nodes", type=int, default=0)
    result.add_argument(
        "--storage-price-per-gib-month",
        type=non_negative,
        default=0.0,
    )
    result.add_argument(
        "--candidate",
        action="append",
        type=candidate,
        help=(
            "Repeat exactly three times: "
            "INSTANCE:MEMORY_GIB:VCPU:EBS_GIB:MONTHLY_PRICE"
        ),
    )
    result.add_argument("--format", choices=("text", "json"), default="text")
    return result


def estimate(args: argparse.Namespace) -> Estimate:
    if args.vector_count <= 0 or args.dimension <= 0:
        raise ValueError("vector-count and dimension must be greater than zero")
    if args.replicas < 0 or args.hnsw_m <= 0 or args.ha_minimum_nodes < 0:
        raise ValueError(
            "replicas and ha-minimum-nodes cannot be negative; hnsw-m must be positive"
        )
    if (args.instance_memory_gib is None) != (args.instance_vcpu is None):
        raise ValueError(
            "instance-memory-gib and instance-vcpu must be supplied together"
        )

    warnings: list[str] = []
    if not 25 <= args.target_primary_shard_gib <= 50:
        warnings.append(
            "target primary shard size is outside the usual 25-50 GiB range"
        )
    if args.non_vector_gib == 0 and args.primary_index_gib is None:
        warnings.append(
            "non-vector data is zero; treat storage and shard results as a lower bound"
        )

    primary_vector_disk_gib = (
        args.vector_disk_gib
        if args.vector_disk_gib is not None
        else (
            args.vector_count
            * args.dimension
            * args.bytes_per_dimension
            / args.vector_disk_compression
            / GIB
        )
    )
    if args.primary_index_gib is not None:
        primary_index_gib = args.primary_index_gib
        primary_index_source = "measured_primary_store"
    else:
        primary_index_gib = (
            primary_vector_disk_gib + args.non_vector_gib
        ) * args.storage_overhead_factor
        primary_index_source = "component_estimate"
    primary_shards = math.ceil(
        primary_index_gib / args.target_primary_shard_gib
    )
    active_shards = primary_shards * (args.replicas + 1)
    required_vcpu = math.ceil(active_shards / args.active_shards_per_vcpu)

    vector_bytes_in_memory = (
        args.dimension * args.bytes_per_dimension / args.memory_compression
    )
    total_knn_memory_gib = (
        1.1
        * (vector_bytes_in_memory + 8 * args.hnsw_m)
        * args.vector_count
        * (args.replicas + 1)
        / GIB
    )
    total_storage_gib = (
        primary_index_gib
        * (args.replicas + 1)
        * args.storage_headroom_factor
    )

    knn_per_node = None
    nodes_by_memory = None
    nodes_by_cpu = None
    if args.instance_memory_gib is not None:
        heap = min(args.instance_memory_gib * 0.5, 32.0)
        knn_per_node = (args.instance_memory_gib - heap) * 0.75
        if knn_per_node <= 0:
            raise ValueError(
                "instance memory leaves no KNN memory after JVM allocation"
            )
        nodes_by_memory = math.ceil(total_knn_memory_gib / knn_per_node)
        nodes_by_cpu = math.ceil(required_vcpu / args.instance_vcpu)

    nodes_by_storage = (
        math.ceil(total_storage_gib / args.ebs_gib_per_node)
        if args.ebs_gib_per_node is not None
        else None
    )
    constraints = {
        "memory": nodes_by_memory,
        "cpu": nodes_by_cpu,
        "storage": nodes_by_storage,
        "availability": args.ha_minimum_nodes,
    }
    known = {key: value for key, value in constraints.items() if value is not None}
    final_nodes = (
        max(known.values())
        if nodes_by_memory is not None and nodes_by_cpu is not None
        else None
    )
    winning = (
        [key for key, value in known.items() if value == final_nodes]
        if final_nodes is not None
        else []
    )
    ebs_per_final_node = (
        total_storage_gib / final_nodes if final_nodes and final_nodes > 0 else None
    )

    return Estimate(
        primary_vector_disk_gib=primary_vector_disk_gib,
        primary_non_vector_gib=args.non_vector_gib,
        primary_index_gib=primary_index_gib,
        primary_index_source=primary_index_source,
        total_provisioned_storage_gib=total_storage_gib,
        primary_shards=primary_shards,
        active_shards=active_shards,
        required_vcpu=required_vcpu,
        total_knn_memory_gib=total_knn_memory_gib,
        knn_memory_available_per_node_gib=knn_per_node,
        nodes_by_memory=nodes_by_memory,
        nodes_by_cpu=nodes_by_cpu,
        nodes_by_storage=nodes_by_storage,
        ha_minimum_nodes=args.ha_minimum_nodes,
        final_data_nodes=final_nodes,
        winning_constraints=winning,
        ebs_gib_per_final_node=ebs_per_final_node,
        warnings=warnings,
    )


def rounded(data: Estimate) -> dict:
    result = asdict(data)
    for key, value in result.items():
        if isinstance(value, float):
            result[key] = round(value, 2)
    return result


def evaluate_candidates(args: argparse.Namespace) -> dict:
    candidates = args.candidate or []
    if len(candidates) != 3:
        raise ValueError("candidate comparison requires exactly three candidates")
    if len({item.instance_type for item in candidates}) != 3:
        raise ValueError("candidate instance types must be different")

    options = []
    common_sizing = None
    for item in candidates:
        candidate_args = copy.copy(args)
        candidate_args.instance_memory_gib = item.memory_gib
        candidate_args.instance_vcpu = item.vcpu
        candidate_args.ebs_gib_per_node = item.ebs_gib_per_node
        candidate_args.candidate = None
        sizing = estimate(candidate_args)
        if common_sizing is None:
            common_sizing = sizing
        if sizing.final_data_nodes is None:
            raise ValueError(f"could not size candidate {item.instance_type}")
        instance_cost = item.monthly_instance_price * sizing.final_data_nodes
        storage_cost = (
            sizing.total_provisioned_storage_gib
            * args.storage_price_per_gib_month
        )
        options.append(
            {
                "instance_type": item.instance_type,
                "node_count": sizing.final_data_nodes,
                "memory_gib_per_node": item.memory_gib,
                "vcpu_per_node": item.vcpu,
                "ebs_limit_gib_per_node": item.ebs_gib_per_node,
                "ebs_required_gib_per_node": sizing.ebs_gib_per_final_node,
                "nodes_by_memory": sizing.nodes_by_memory,
                "nodes_by_cpu": sizing.nodes_by_cpu,
                "nodes_by_storage": sizing.nodes_by_storage,
                "ha_minimum_nodes": sizing.ha_minimum_nodes,
                "winning_constraints": sizing.winning_constraints,
                "monthly_instance_cost": instance_cost,
                "monthly_storage_cost": storage_cost,
                "estimated_monthly_total": instance_cost + storage_cost,
            }
        )

    options.sort(
        key=lambda item: item["estimated_monthly_total"],
        reverse=True,
    )
    for order, option in enumerate(options, start=1):
        option["cost_order_high_to_low"] = order
        for key, value in option.items():
            if isinstance(value, float):
                option[key] = round(value, 2)
    assert common_sizing is not None
    return {
        "shared_assumptions": {
            "vector_count": args.vector_count,
            "dimension": args.dimension,
            "memory_compression": args.memory_compression,
            "replicas": args.replicas,
            "target_primary_shard_gib": args.target_primary_shard_gib,
            "active_shards_per_vcpu": args.active_shards_per_vcpu,
            "primary_index_gib": round(common_sizing.primary_index_gib, 2),
            "primary_shards": common_sizing.primary_shards,
            "active_shards": common_sizing.active_shards,
            "required_vcpu": common_sizing.required_vcpu,
            "total_knn_memory_gib": round(
                common_sizing.total_knn_memory_gib, 2
            ),
            "total_provisioned_storage_gib": round(
                common_sizing.total_provisioned_storage_gib, 2
            ),
        },
        "options": options,
        "recommendation": (
            "No automatic performance recommendation from capacity and cost alone. "
            "Use QPS, P95/P99 latency, recall, and benchmark results to recommend "
            "one option separately; do not assume the cheapest option is best."
        ),
    }


def print_text(data: Estimate) -> None:
    values = rounded(data)
    print("OpenSearch vector resource estimate")
    print(f"Primary vector disk: {values['primary_vector_disk_gib']} GiB")
    print(f"Primary non-vector data: {values['primary_non_vector_gib']} GiB")
    print(
        f"Primary index: {values['primary_index_gib']} GiB "
        f"({data.primary_index_source})"
    )
    print(
        "Provisioned storage including replicas/headroom: "
        f"{values['total_provisioned_storage_gib']} GiB"
    )
    print(f"Primary / active shards: {data.primary_shards} / {data.active_shards}")
    print(f"Required vCPU from active shards: {data.required_vcpu}")
    print(f"Total KNN memory: {values['total_knn_memory_gib']} GiB")
    if data.final_data_nodes is not None:
        print(
            "Node floors (memory/cpu/storage/HA): "
            f"{data.nodes_by_memory}/{data.nodes_by_cpu}/"
            f"{data.nodes_by_storage}/{data.ha_minimum_nodes}"
        )
        print(f"Final data nodes: {data.final_data_nodes}")
        print(f"Winning constraint(s): {', '.join(data.winning_constraints)}")
        print(f"EBS per final node: {values['ebs_gib_per_final_node']} GiB")
    else:
        print(
            "Final node count requires candidate instance memory and vCPU inputs; "
            "storage also requires an EBS-per-node limit to become a node floor."
        )
    for warning in data.warnings:
        print(f"Warning: {warning}")


def print_candidate_options(report: dict) -> None:
    assumptions = report["shared_assumptions"]
    print("Shared assumptions")
    print(
        f"Vectors/dimension/compression: {assumptions['vector_count']} / "
        f"{assumptions['dimension']} / {assumptions['memory_compression']}x"
    )
    print(
        f"Replicas/shard target/shards per vCPU: {assumptions['replicas']} / "
        f"{assumptions['target_primary_shard_gib']} GiB / "
        f"{assumptions['active_shards_per_vcpu']}"
    )
    print(
        f"Primary index/shards/active shards: "
        f"{assumptions['primary_index_gib']} GiB / "
        f"{assumptions['primary_shards']} / {assumptions['active_shards']}"
    )
    print(
        f"Required vCPU/KNN memory/provisioned storage: "
        f"{assumptions['required_vcpu']} / "
        f"{assumptions['total_knn_memory_gib']} GiB / "
        f"{assumptions['total_provisioned_storage_gib']} GiB"
    )
    print()
    print("Three valid instance options (estimated monthly cost: high to low)")
    for option in report["options"]:
        print(
            f"{option['cost_order_high_to_low']}. {option['instance_type']} × "
            f"{option['node_count']}: ${option['estimated_monthly_total']}/month"
        )
        print(
            f"   Per node: {option['vcpu_per_node']} vCPU, "
            f"{option['memory_gib_per_node']} GiB RAM, "
            f"{option['ebs_required_gib_per_node']} GiB EBS required"
        )
        print(
            "   Node floors memory/cpu/storage/HA: "
            f"{option['nodes_by_memory']}/{option['nodes_by_cpu']}/"
            f"{option['nodes_by_storage']}/{option['ha_minimum_nodes']}; "
            f"winner: {', '.join(option['winning_constraints'])}"
        )
        print(
            f"   Compute ${option['monthly_instance_cost']} + "
            f"storage ${option['monthly_storage_cost']}"
        )
    print("Costs exclude provisioned IOPS, throughput, and data transfer.")
    print(f"Recommendation: {report['recommendation']}")


def main() -> None:
    args = parser().parse_args()
    try:
        if args.candidate:
            report = evaluate_candidates(args)
            if args.format == "json":
                print(json.dumps(report, indent=2))
            else:
                print_candidate_options(report)
            return
        result = estimate(args)
    except ValueError as exc:
        parser().error(str(exc))
    if args.format == "json":
        print(json.dumps(rounded(result), indent=2))
    else:
        print_text(result)


if __name__ == "__main__":
    main()
