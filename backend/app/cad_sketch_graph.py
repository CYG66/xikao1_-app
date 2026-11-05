"""Isolated SketchGraph candidates for generic 2D CAD construction.

The graph is a symbolic, read-only layer above ``CadConstructionPlan``.  It
does not persist projects or variants.  Each candidate is executed in its own
deterministic working state, then represented as object/segment nodes with
dependency, containment and continuity edges.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cad_construction import (
    AddCompositePathStep,
    CadConstructionPlan,
    ConstructionPlanError,
    RectangularArrayStep,
    execute_construction_plan,
)
from .cad_visual_scoring import score_candidate_visuals


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SketchGraphCandidate(_StrictModel):
    candidate_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$",
    )
    title: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=500)
    plan: CadConstructionPlan


class SketchGraphCandidateSet(_StrictModel):
    schema_version: Literal["cad.sketchgraph-candidates.v1"] = (
        "cad.sketchgraph-candidates.v1"
    )
    requirement: str = Field(min_length=1, max_length=4000)
    candidates: list[SketchGraphCandidate] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> "SketchGraphCandidateSet":
        values = [item.candidate_id for item in self.candidates]
        if len(values) != len(set(values)):
            raise ValueError("candidate_id values must be unique")
        return self


class SketchGraphNode(_StrictModel):
    node_id: str = Field(min_length=1, max_length=160)
    kind: Literal["drawing", "object", "segment"]
    primitive: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    output_ref: str | None = Field(default=None, max_length=128)
    geometry_ids: list[int] = Field(default_factory=list, max_length=5000)


class SketchGraphEdge(_StrictModel):
    edge_id: str = Field(min_length=1, max_length=200)
    relation: Literal["contains", "depends_on", "connected_to", "closes_to"]
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)


class SketchGraphConstraint(_StrictModel):
    constraint_id: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=64)
    target_ref: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SketchGraph(_StrictModel):
    schema_version: Literal["cad.sketchgraph.v1"] = "cad.sketchgraph.v1"
    graph_id: str = Field(min_length=1, max_length=100)
    nodes: list[SketchGraphNode] = Field(min_length=1, max_length=10000)
    edges: list[SketchGraphEdge] = Field(default_factory=list, max_length=20000)
    constraints: list[SketchGraphConstraint] = Field(
        default_factory=list, max_length=100,
    )

    @model_validator(mode="after")
    def validate_graph_references(self) -> "SketchGraph":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("SketchGraph node_id values must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
        return self


def sketch_graph_candidate_set_json_schema() -> dict[str, Any]:
    """Return the exact structured-output schema for 2-3 graph candidates."""
    return SketchGraphCandidateSet.model_json_schema()


def evaluate_sketch_graph_candidates(
    candidate_set: SketchGraphCandidateSet | dict[str, Any],
) -> dict[str, Any]:
    """Execute, graph and rank 2-3 candidates without persisting any state."""
    validated = (
        candidate_set
        if isinstance(candidate_set, SketchGraphCandidateSet)
        else SketchGraphCandidateSet.model_validate(candidate_set)
    )
    records: list[dict[str, Any]] = []
    first_by_fingerprint: dict[str, str] = {}
    for source_index, candidate in enumerate(validated.candidates):
        try:
            trial = execute_construction_plan(candidate.plan)
            graph = build_sketch_graph(candidate, trial)
            fingerprint = _geometry_fingerprint(trial["geometries"])
            duplicate_of = first_by_fingerprint.get(fingerprint)
            if duplicate_of is None:
                first_by_fingerprint[fingerprint] = candidate.candidate_id
            score, evidence = _candidate_score(trial)
            visual_score = score_candidate_visuals(list(trial.get("geometries") or []))
            records.append({
                "candidate_id": candidate.candidate_id,
                "title": candidate.title,
                "rationale": candidate.rationale,
                "status": "duplicate" if duplicate_of else "valid",
                "score": score,
                "score_evidence": evidence,
                "visual_score": visual_score,
                "duplicate_of": duplicate_of,
                "source_index": source_index,
                "graph": graph.model_dump(mode="json"),
                "trial_result": deepcopy(trial),
                "error": None,
            })
        except ConstructionPlanError as exc:
            records.append({
                "candidate_id": candidate.candidate_id,
                "title": candidate.title,
                "rationale": candidate.rationale,
                "status": "invalid",
                "score": 0.0,
                "score_evidence": {"verified": False},
                "visual_score": None,
                "duplicate_of": None,
                "source_index": source_index,
                "graph": None,
                "trial_result": None,
                "error": exc.as_dict(),
            })
        except Exception as exc:
            # A malformed candidate must not prevent the remaining independent
            # candidates from being executed and compared.
            records.append({
                "candidate_id": candidate.candidate_id,
                "title": candidate.title,
                "rationale": candidate.rationale,
                "status": "invalid",
                "score": 0.0,
                "score_evidence": {"verified": False},
                "visual_score": None,
                "duplicate_of": None,
                "source_index": source_index,
                "graph": None,
                "trial_result": None,
                "error": {
                    "code": "candidate_evaluation_failed",
                    "message": str(exc),
                },
            })

    eligible = [item for item in records if item["status"] == "valid"]
    ranked = sorted(
        eligible,
        key=lambda item: (
            -float(item["score"]),
            -float((item.get("visual_score") or {}).get("score", 0.0)),
            int(item["source_index"]),
        ),
    )
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    for item in records:
        item.setdefault("rank", None)
    recommended = ranked[0]["candidate_id"] if ranked else None
    return {
        "schema": "cad.sketchgraph-candidate-evaluation.v1",
        "requirement": validated.requirement,
        "read_only": True,
        "project_persistence": False,
        "candidate_count": len(records),
        "valid_candidate_count": len(eligible),
        "duplicate_candidate_count": sum(
            item["status"] == "duplicate" for item in records
        ),
        "invalid_candidate_count": sum(
            item["status"] == "invalid" for item in records
        ),
        "recommended_candidate_id": recommended,
        "candidates": records,
    }


def build_sketch_graph(
    candidate: SketchGraphCandidate,
    trial_result: dict[str, Any],
) -> SketchGraph:
    """Build graph topology from one validated plan and execution result."""
    root_id = f"graph:{candidate.candidate_id}"
    nodes: list[SketchGraphNode] = [SketchGraphNode(
        node_id=root_id,
        kind="drawing",
        primitive="drawing",
        label=candidate.title,
    )]
    edges: list[SketchGraphEdge] = []
    refs = trial_result.get("symbol_table") or {}
    output_nodes: dict[str, str] = {}
    edge_index = 1

    def add_edge(relation: str, source: str, target: str) -> None:
        nonlocal edge_index
        edges.append(SketchGraphEdge(
            edge_id=f"edge:{edge_index}",
            relation=relation,
            source=source,
            target=target,
        ))
        edge_index += 1

    for step in candidate.plan.steps:
        node_id = f"object:{step.output_ref}"
        output_nodes[step.output_ref] = node_id
        nodes.append(SketchGraphNode(
            node_id=node_id,
            kind="object",
            primitive=step.op,
            label=step.semantic.label,
            output_ref=step.output_ref,
            geometry_ids=[int(value) for value in refs.get(step.output_ref, [])],
        ))
        add_edge("contains", root_id, node_id)
        if isinstance(step, RectangularArrayStep):
            source_node = output_nodes.get(step.source_ref)
            if source_node is not None:
                add_edge("depends_on", node_id, source_node)
        if isinstance(step, AddCompositePathStep):
            segment_ids: list[str] = []
            for index, segment in enumerate(step.segments, start=1):
                segment_id = f"segment:{step.output_ref}:{index}"
                segment_ids.append(segment_id)
                nodes.append(SketchGraphNode(
                    node_id=segment_id,
                    kind="segment",
                    primitive=segment.kind,
                    label=f"{step.semantic.label} 第{index}段",
                    output_ref=step.output_ref,
                ))
                add_edge("contains", node_id, segment_id)
            for left, right in zip(segment_ids, segment_ids[1:]):
                add_edge("connected_to", left, right)
            if step.closed and len(segment_ids) > 1:
                add_edge("closes_to", segment_ids[-1], segment_ids[0])

    constraints = []
    for solved_constraint in candidate.plan.constraints:
        payload = solved_constraint.model_dump(mode="json")
        constraints.append(SketchGraphConstraint(
            constraint_id=str(payload.pop("constraint_id")),
            kind=str(payload.pop("kind")),
            target_ref=payload.pop("target_ref", None),
            parameters=payload,
        ))
    for assertion in candidate.plan.assertions:
        payload = assertion.model_dump(mode="json")
        constraints.append(SketchGraphConstraint(
            constraint_id=str(payload.pop("assertion_id")),
            kind=str(payload.pop("kind")),
            target_ref=payload.pop("target_ref", None),
            parameters=payload,
        ))
    return SketchGraph(
        graph_id=root_id,
        nodes=nodes,
        edges=edges,
        constraints=constraints,
    )


def _candidate_score(trial: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    assertion_count = int((trial.get("assertions") or {}).get("count", 0))
    constraint_count = int((trial.get("constraint_solve") or {}).get("constraint_count", 0))
    quality = list(trial.get("curve_quality") or [])
    warning_count = len((trial.get("feasibility") or {}).get("warnings") or [])
    score = max(
        0.0,
        100.0
        + min(10, assertion_count) * 2.0
        + min(10, constraint_count) * 2.0
        + (5.0 if quality and all(item.get("verified") for item in quality) else 0.0)
        - min(20, warning_count * 2),
    )
    return round(score, 3), {
        "verified": True,
        "assertion_count": assertion_count,
        "constraint_count": constraint_count,
        "curve_quality_report_count": len(quality),
        "feasibility_warning_count": warning_count,
        "visual_score_used": True,
        "visual_score_role": "geometry_score_tie_break_only",
        "visual_score_is_authoritative": False,
        "geometry_is_authoritative": True,
    }


def _geometry_fingerprint(geometries: list[dict[str, Any]]) -> str:
    normalized = []
    for geometry in geometries:
        item = deepcopy(geometry)
        item.pop("id", None)
        normalized.append(item)
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
