from copy import deepcopy
import pytest
from app.cad_constraint_solver import solve_geometric_constraints, ConcentricConstraint, ConstraintSolveError
from app.cad_construction_interpreter import construction_acceptance_summary

@pytest.mark.parametrize("refs", [("A", "B"), ("B", "A")])
def test_conflicting_centers_fail_in_both_orders(refs):
    geometries = [{"id": i, "type": "circle", "center": {"x": x, "y": 0}, "radius": 1} for i, x in enumerate((0, 10, 3))]
    original = deepcopy(geometries)
    constraints = [ConcentricConstraint(kind="concentric", constraint_id=str(i), target_ref="C", reference_ref=r) for i, r in enumerate(refs)]
    with pytest.raises(ConstraintSolveError) as error:
        solve_geometric_constraints(geometries, {"A": [0], "B": [1], "C": [2]}, constraints, unit_scale=1, backend="builtin")
    assert error.value.code == "constraint_residual_exceeded"
    assert geometries == original

@pytest.mark.parametrize("source", [{}, {"status": "review_required", "review_required": True}, {"coverage": "partial", "checks": [{"status": "passed"}]}])
def test_execution_cannot_promote_missing_or_partial_coverage(source):
    result = construction_acceptance_summary(preflight_structure=None, structure_contract=None, structure_validation=None, composition_contract=None, composition_validation=None, source_acceptance=source, trial_result={"assertions": {"ok": True}, "feasibility": {"ok": True}})
    assert result["status"] == "review_required"
    assert result["review_required"] is True
