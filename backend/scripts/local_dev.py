"""Repository-local development entry point; no dependency on shell activation."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.local-dev'
CAD_TESTS = [
    'test_named_primitive_edit_binding.py',
    'test_edit_preview_routing.py',
    'test_arch_boundary_repair_handoff.py',
    'test_arch_language_handoff.py',
    'test_vertex_path_language_handoff.py',
    'test_circle_group_output_handoff.py',
    'test_output_intent_recovery.py',
    'test_path_source_contract_handoff.py',
    'test_failed_source_retention.py',
    'test_full_segment_replan.py',
    'test_model_bounds_authority.py',
    'test_planning_unit_contract.py',
    'test_tangent_endpoint_angles.py',
    'test_frozen_holdout_handoff.py',
    'test_cad_requirement_ledger.py',
    'test_business_measurement_consolidation.py',
    'test_merge_first_three.py',
    'test_cad_shared_points.py',
    'test_source_delivery_precision.py',
    'test_arch_source_generalization.py',
    'test_open_path_source_generalization.py',
    'test_capsule_source_generalization.py',
    'test_repair_reference_handoff.py',
    'test_cad_tool_contract_handoff.py',
    'test_construction_failure_evidence.py',
    'test_symmetric_divider_source.py',
    'test_radial_attachment_source.py',
    'test_cad_projection_acceptance.py',
    'test_source_readiness_and_invariant_edits.py',
    'test_primitive_layout_source_handoff.py',
    'test_cad_relation_acceptance.py',
    'test_polar_wave_source_handoff.py',
    'test_cad_parametric.py',
    'test_stroke_source_handoff.py',
    'test_cad_stroke_acceptance.py',
    'test_repetition_source_handoff.py',
    'test_cad_repetition_acceptance.py',
    'test_measured_semantic_source_handoff.py',
    'test_outline_binding_handoff.py',
    'test_outline_delivery_source.py',
    'test_remaining_source_binding.py',
    'test_business_oracles_v2.py',
    'test_project_user_source_binding.py',
    'test_regression_source_handoff.py',
    'test_curve_joint_and_array_feedback.py',
    'test_c3_c6_c33_repairs.py',
    'test_source_size_snapshot_authority.py',
    'test_confirmed_source_repair.py',
    'test_closed_boundary_oracle_v3.py',
    'test_acceptance_boundaries.py',
    'test_construction_quality.py',
    'test_vertex_array_source_handoff.py',
    'test_rectangle_source_handoff.py',
    'test_composition_coverage_handoff.py',
    'test_component_dimension_scope_handoff.py',
    'test_control_point_source_handoff.py',
    'test_single_primitive_source_handoff.py',
    'test_ellipse_axis_handoff.py',
    'test_cad_requirement_contract.py',
    'test_cad_source_acceptance.py',
    'test_cad_structure_contract.py',
    'test_cad_construction_interpreter.py',
    'test_cad_construction_commit.py',
    'test_cad_template_plan.py',
    'test_candidate_visibility_gate.py',
]


def isolated_environment(action: str, live: bool) -> tuple[dict[str, str], Path]:
    RUNTIME.mkdir(exist_ok=True)
    state = RUNTIME / 'server' if action == 'serve' else Path(
        tempfile.mkdtemp(prefix=f'{action}-', dir=RUNTIME)
    )
    for name in ('home', 'tmp', 'cad', 'attachments', 'planned_results', 'workspace'):
        (state / name).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
        'PYTHONPATH': str(ROOT), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'HOME': str(state / 'home'), 'USERPROFILE': str(state / 'home'),
        'XDG_STATE_HOME': str(state), 'TEMP': str(state / 'tmp'),
        'TMP': str(state / 'tmp'), 'XLINE_RUNTIME_PROFILE': 'virtual_sim',
        'XLINE_EMBEDDED_DISCOVERY': '0', 'XLINE_ENABLE_PRINTER': '0',
        'XLINE_USE_TOTAL_STATION': '0', 'XLINE_VIRTUAL_TOTAL_STATION': '0',
        'XLINE_AGENT_PROVIDER': 'deepseek' if live else 'local',
        'XLINE_CAD_DIR': str(state / 'cad'),
        'XLINE_AGENT_ATTACHMENTS_DIR': str(state / 'attachments'),
        'XLINE_PLANNED_RESULTS_DIR': str(state / 'planned_results'),
        'XLINE_WS_DIR': str(state / 'workspace'),
        'XLINE_WS_ROOT': str(state / 'workspace'),
        'XLINE_DATABASE_PATH': str(state / 'backend.db'),
        'XLINE_AGENT_TASK_STORE': str(state / 'tasks.json'),
        'XLINE_AGENT_AUDIT_STORE': str(state / 'audit.jsonl'),
        'XLINE_AGENT_RUN_STORE': str(state / 'runs.json'),
        'XLINE_AGENT_PLAN_STORE': str(state / 'plans.sqlite'),
        'XLINE_AGENT_MEMORY_STORE': str(state / 'memory.json'),
        'XLINE_CREATIVE_PROJECT_STORE': str(state / 'projects.json'),
        'XLINE_DRAWING_VERSION_STORE': str(state / 'versions.json'),
        'XLINE_MISSION_LEDGER_STORE': str(state / 'missions.json'),
        'XLINE_AGENT_USER_CONFIG_PATH': str(state / 'home' / 'users.json'),
    })
    for name in ('DEEPSEEK_MODEL', 'DEEPSEEK_BASE_MODEL',
                 'DEEPSEEK_ADVANCED_MODEL', 'DEEPSEEK_CAD_PLANNING_MODEL'):
        env[name] = 'deepseek-flash'
    if not live:
        for name in list(env):
            if name.endswith('_API_KEY') or name.endswith('_API_KEYS'):
                env.pop(name)
    return env, state


def run(command: list[str], env: dict[str, str]) -> int:
    return subprocess.call(command, cwd=ROOT, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'check', 'test', 'serve'])
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error('Use the dedicated test environment with Python 3.11.')
    if args.live and args.action != 'serve':
        parser.error('--live is only supported for serve.')
    if args.live and not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        parser.error('Set DEEPSEEK_API_KEY in the current shell before live serving.')
    if args.action == 'setup':
        code = run([sys.executable, '-m', 'pip', 'install', '-r',
                    str(ROOT / 'requirements-dev.txt')], os.environ.copy())
        if code:
            return code
        args.action = 'check'
    env, state = isolated_environment(args.action, args.live)
    print(f'Backend: {ROOT}\nPython: {sys.executable}\nState: {state}', flush=True)
    if args.action == 'serve':
        return run([sys.executable, '-m', 'uvicorn', 'app.main:app',
                    '--host', '127.0.0.1', '--port', str(args.port)], env)
    if args.action == 'check':
        code = run([sys.executable, '-m', 'pip', 'check'], env)
        if code:
            return code
        return run([sys.executable, str(ROOT / 'scripts' / 'smoke_local.py')], env)
    log = state / 'pytest.log'
    command = [sys.executable, '-m', 'pytest',
               *[str(ROOT / 'tests' / name) for name in CAD_TESTS],
               '-q', '-ra', '--tb=short', f'--junitxml={state / "junit.xml"}']
    started = datetime.now().isoformat()
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end='')
            output.write(line)
        code = process.wait()
    (state / 'result.json').write_text(json.dumps({
        'backend': str(ROOT), 'python': sys.executable, 'started': started,
        'finished': datetime.now().isoformat(), 'exit_code': code,
        'command': command, 'log': str(log),
        'scope': 'Offline CAD regression; not the 70-case live corpus pass rate',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {state / "result.json"}')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
