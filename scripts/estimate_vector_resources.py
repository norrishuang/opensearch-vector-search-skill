#!/usr/bin/env python3
"""Estimate OpenSearch vector resources from storage, shards, CPU, and KNN memory."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass


GIB = 1024**3


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


def main() -> None:
    args = parser().parse_args()
    try:
        result = estimate(args)
    except ValueError as exc:
        parser().error(str(exc))
    if args.format == "json":
        print(json.dumps(rounded(result), indent=2))
    else:
        print_text(result)


if __name__ == "__main__":
    main()
