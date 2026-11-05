import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.rosbridge_protocol as main_module
import app.ros_adapter as ros_adapter_module
from app.mission_ledger import MissionLedgerStore
from app.ros_adapter import RobotBackendNode
from app.state import (
    load_virtual_mission_segments,
    robot_state,
    start_virtual_mission_tracking,
    tick_demo_state,
)


class VirtualSimProfileTest(unittest.TestCase):
    def setUp(self):
        self.node = object.__new__(RobotBackendNode)
        self.node.calibration_client = None
        self.node.get_node_names = lambda: [
            'differential_wheels_driver', 'cmd_vel_mux', 'drawing_planner_node',
            'motion_control_center', 'odom_imu_localization', 'inkjet_printer_node',
        ]

    def test_virtual_profile_does_not_require_can0(self):
        with patch.object(ros_adapter_module, 'RUNTIME_PROFILE', 'virtual_sim'):
            self.node._update_graph_readiness()
        self.assertEqual(robot_state.drive_transport, 'virtual')
        self.assertTrue(robot_state.drive_device_connected)
        self.assertTrue(robot_state.mission_nodes_ready)

    def test_adapter_starts_complete_virtual_state_without_ros2(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        with patch.object(ros_adapter_module, 'RUNTIME_PROFILE', 'virtual_sim'):
            adapter.start()
            try:
                self.assertEqual(robot_state.bridge_mode, 'virtual_ros2')
                self.assertTrue(robot_state.control_ready)
                self.assertEqual(robot_state.energy_source, 'virtual_bms')
                self.assertIsNotNone(robot_state.battery)
                self.assertTrue(robot_state.printer_ready)
                self.assertTrue(robot_state.localization_valid)
            finally:
                adapter.stop()

    def test_virtual_profile_can_release_and_reapply_emergency_stop(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        with patch.object(ros_adapter_module, 'RUNTIME_PROFILE', 'virtual_sim'):
            adapter.start()
            try:
                self.assertTrue(robot_state.emergency_stopped)
                self.assertTrue(adapter.set_emergency_stop(False))
                self.assertFalse(robot_state.emergency_stopped)
                self.assertTrue(adapter.set_emergency_stop(True))
                self.assertTrue(robot_state.emergency_stopped)
            finally:
                adapter.stop()

    def test_virtual_total_station_reports_ln150_and_supports_calibration(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        with patch.object(ros_adapter_module, 'RUNTIME_PROFILE', 'virtual_sim'), \
             patch.object(ros_adapter_module, 'VIRTUAL_TOTAL_STATION', True), \
             patch('app.state.VIRTUAL_TOTAL_STATION', True):
            adapter.start()
            try:
                self.assertEqual(robot_state.localization_source, 'ln150_imu')
                self.assertTrue(robot_state.ln150_ready)
                self.assertTrue(robot_state.localization_calibration_available)
                self.assertTrue(adapter.prepare_localization_calibration())
                self.assertEqual(robot_state.localization_calibration, 'sampling')
                self.assertTrue(adapter.calibrate_localization())
                self.assertEqual(robot_state.localization_calibration, 'accepted')
            finally:
                adapter.stop()

    def test_virtual_vehicle_follows_loaded_mission_segments(self):
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.emergency_stopped = False
        robot_state.robot_pose = {'frame_id': 'map', 'x': 0.0, 'y': 0.0, 'theta': 0.0}
        robot_state.printer_status = {'printer_center': {'spraying': False}}
        load_virtual_mission_segments([
            {'route_type': 'transition', 'points': [[0.0, 0.0], [0.2, 0.0]]},
            {'route_type': 'printing', 'points': [[0.2, 0.0], [0.2, 0.2]]},
        ])
        self.assertTrue(start_virtual_mission_tracking())
        robot_state.mission_running = True
        robot_state.mission_paused = False

        tick_demo_state(delta_seconds=1.0)
        self.assertAlmostEqual(robot_state.robot_pose['x'], 0.1, places=3)
        self.assertAlmostEqual(robot_state.robot_pose['y'], 0.0, places=3)
        self.assertFalse(robot_state.printer_status['printer_center']['spraying'])

        tick_demo_state(delta_seconds=2.0)
        self.assertAlmostEqual(robot_state.robot_pose['x'], 0.2, places=3)
        self.assertAlmostEqual(robot_state.robot_pose['y'], 0.1, places=3)
        self.assertEqual(robot_state.mission_completed, 1)
        self.assertTrue(robot_state.printer_status['printer_center']['spraying'])

        tick_demo_state(delta_seconds=1.0)
        self.assertFalse(robot_state.mission_running)
        self.assertEqual(robot_state.mission_stage, 'completed')
        self.assertEqual(robot_state.mission_completed, 2)
        self.assertFalse(robot_state.printer_status['printer_center']['spraying'])

    def test_virtual_vehicle_does_not_move_while_paused_or_stopped(self):
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.robot_pose = {'frame_id': 'map', 'x': 0.0, 'y': 0.0, 'theta': 0.0}
        load_virtual_mission_segments([
            {'route_type': 'printing', 'points': [[0.0, 0.0], [1.0, 0.0]]},
        ])
        self.assertTrue(start_virtual_mission_tracking())
        robot_state.mission_running = True
        robot_state.mission_paused = True
        robot_state.emergency_stopped = False
        tick_demo_state(delta_seconds=2.0)
        self.assertEqual(robot_state.robot_pose['x'], 0.0)

    def test_virtual_mission_writes_ledger_segments_trace_and_report(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.emergency_stopped = False
        robot_state.localization_valid = True
        robot_state.localization_source = 'virtual_odom_imu'
        robot_state.robot_pose = {'frame_id': 'map', 'x': 0.0, 'y': 0.0, 'theta': 0.0}
        robot_state.printer_status = {
            'printer_center': {'connected': True, 'enabled': True, 'spraying': False},
        }
        planned = [
            {'route_type': 'transition', 'points': [[0.0, 0.0], [0.1, 0.0]]},
            {'route_type': 'printing', 'points': [[0.1, 0.0], [0.1, 0.1]]},
        ]

        with tempfile.TemporaryDirectory() as directory:
            ledger = MissionLedgerStore(Path(directory) / 'virtual-ledger.json')
            with patch.object(ros_adapter_module, 'mission_ledger', ledger), \
                 patch.object(ros_adapter_module.drawing_versions, 'find_by_file', return_value=None):
                load_virtual_mission_segments(planned)
                adapter._create_virtual_mission_ledger('virtual.json', planned)
                robot_state.mission_plan_generation += 1
                robot_state.mission_file = 'virtual.json'
                robot_state.mission_stage = 'ready'
                robot_state.mission_prepared_file = 'virtual.json'
                robot_state.mission_prepared_generation = robot_state.mission_plan_generation
                mission_id = robot_state.mission_ledger_id
                self.assertIsNotNone(mission_id)
                self.assertEqual(ledger.get(mission_id)['state'], 'ready')

                self.assertTrue(adapter.control_mission_action('start', 'virtual.json'))
                self.assertEqual(ledger.get(mission_id)['state'], 'executing')
                self.assertEqual(ledger.get(mission_id)['segments'][0]['state'], 'executing')

                adapter._tick_virtual_sim_once(delta_seconds=5.0)
                mission = ledger.get(mission_id)
                self.assertEqual(mission['state'], 'completed')
                self.assertEqual(mission['execution_mode'], 'virtual_sim')
                self.assertEqual(
                    [segment['state'] for segment in mission['segments']],
                    ['completed', 'completed'],
                )
                self.assertTrue(all(segment['precheck']['virtual'] for segment in mission['segments']))
                self.assertTrue(all(segment['verification']['virtual'] for segment in mission['segments']))
                self.assertGreaterEqual(len(mission['actual_trace']), 2)
                self.assertEqual(mission['report']['final_state'], 'completed')
                self.assertEqual(mission['report']['execution_mode'], 'virtual_sim')
                self.assertEqual(mission['report']['verdict'], 'accepted')
                self.assertEqual(ledger.reports()[0]['mission_id'], mission_id)

    def test_virtual_mission_cancel_generates_incomplete_report(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.emergency_stopped = False
        robot_state.localization_valid = True
        robot_state.localization_source = 'virtual_odom_imu'
        robot_state.robot_pose = {'frame_id': 'map', 'x': 0.0, 'y': 0.0, 'theta': 0.0}
        robot_state.printer_status = {
            'printer_center': {'connected': True, 'enabled': True, 'spraying': False},
        }
        planned = [
            {'route_type': 'printing', 'points': [[0.0, 0.0], [1.0, 0.0]]},
        ]

        with tempfile.TemporaryDirectory() as directory:
            ledger = MissionLedgerStore(Path(directory) / 'virtual-ledger.json')
            with patch.object(ros_adapter_module, 'mission_ledger', ledger), \
                 patch.object(ros_adapter_module.drawing_versions, 'find_by_file', return_value=None):
                load_virtual_mission_segments(planned)
                adapter._create_virtual_mission_ledger('virtual.json', planned)
                robot_state.mission_plan_generation += 1
                robot_state.mission_file = 'virtual.json'
                robot_state.mission_stage = 'ready'
                robot_state.mission_prepared_file = 'virtual.json'
                robot_state.mission_prepared_generation = robot_state.mission_plan_generation
                mission_id = robot_state.mission_ledger_id
                self.assertTrue(adapter.control_mission_action('start', 'virtual.json'))
                self.assertTrue(adapter.control_mission_action('cancel', 'virtual.json'))

                mission = ledger.get(mission_id)
                self.assertEqual(mission['state'], 'cancelled')
                self.assertEqual(mission['report']['final_state'], 'cancelled')
                self.assertEqual(mission['report']['verdict'], 'incomplete')

        robot_state.mission_paused = False
        robot_state.emergency_stopped = True
        tick_demo_state(delta_seconds=2.0)
        self.assertEqual(robot_state.robot_pose['x'], 0.0)

    def test_virtual_start_prepares_selected_drawing_when_segments_are_missing(self):
        adapter = ros_adapter_module.RobotRosAdapter()
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.emergency_stopped = False
        robot_state.localization_valid = True
        robot_state.localization_source = 'virtual_odom_imu'
        robot_state.robot_pose = {'frame_id': 'map', 'x': 0.0, 'y': 0.0, 'theta': 0.0}
        robot_state.printer_status = {
            'printer_center': {'connected': True, 'enabled': True, 'spraying': False},
        }
        load_virtual_mission_segments([])

        def prepare(file_name):
            self.assertEqual(file_name, 'selected.json')
            robot_state.mission_plan_generation += 1
            robot_state.mission_file = file_name
            robot_state.mission_stage = 'ready'
            robot_state.mission_prepared_file = file_name
            robot_state.mission_prepared_generation = robot_state.mission_plan_generation
            robot_state.planned_paths = [
                {'route_type': 'printing', 'points': [[0.0, 0.0], [1.0, 0.0]]},
            ]
            load_virtual_mission_segments(robot_state.planned_paths)
            return True

        with patch.object(adapter, 'prepare_mission', side_effect=prepare) as mocked_prepare, \
             patch.object(adapter, '_start_virtual_ledger_segment', return_value=True):
            self.assertTrue(adapter.control_mission_action('start', 'selected.json'))

        mocked_prepare.assert_called_once_with('selected.json')
        self.assertTrue(robot_state.mission_running)
        self.assertEqual(robot_state.mission_file, 'selected.json')

    def test_websocket_mission_control_uses_virtual_mission_controller(self):
        robot_state.bridge_mode = 'virtual_ros2'
        robot_state.mission_error = ''
        payload = {
            'op': 'mission_control',
            'action': 'start',
            'file_name': 'virtual.json',
            'client_id': 'virtual-client',
        }
        with patch.object(main_module.ros_adapter, 'owns_control', return_value=True), \
             patch.object(
                 main_module,
                 'authorize_tool',
                 return_value=SimpleNamespace(allowed=True, message=''),
             ), \
             patch.object(
                 main_module.ros_adapter,
                 'control_mission_action',
                 return_value=True,
             ) as control:
            response = main_module.handle_rosbridge_payload(payload)

        control.assert_called_once_with('start', 'virtual.json')
        self.assertTrue(response['ok'])
        self.assertEqual(response['message'], 'virtual mission updated')


if __name__ == '__main__':
    unittest.main()
