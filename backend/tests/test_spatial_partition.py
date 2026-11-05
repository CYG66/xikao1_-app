from __future__ import annotations

import unittest

from app.spatial_partition import (
    build_spatial_partition,
    next_partition_segment,
    next_partition_zone,
    update_partition_segment,
    update_partition_zone,
)


class SpatialPartitionTest(unittest.TestCase):
    def test_cross_zone_line_preserves_identity_length_and_continuity(self) -> None:
        geometries = [
            {
                "id": 7,
                "type": "line",
                "layer_id": 1,
                "label": "主划线",
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 120000.0, "y": 0.0, "z": 0.0},
            }
        ]
        scale = {
            "requires_partitioning": True,
            "work_zone_size_m": 50.0,
            "suggested_rows": 1,
            "suggested_columns": 3,
        }

        partition = build_spatial_partition(
            "variant-1",
            geometries,
            [{"object_id": "main-line", "label": "主划线", "geometry_refs": [7]}],
            {},
            scale,
        )
        repeated = build_spatial_partition(
            "variant-1",
            geometries,
            [{"object_id": "main-line", "label": "主划线", "geometry_refs": [7]}],
            {},
            scale,
        )

        self.assertEqual(partition, repeated)
        self.assertEqual(partition["status"], "ready")
        self.assertTrue(partition["coverage"]["verified"])
        self.assertEqual(partition["coverage"]["duplicate_printing_segments"], 0)
        self.assertEqual(partition["coverage"]["length_delta_m"], 0.0)
        construction = [
            zone for zone in partition["zones"] if zone["status"] != "not_required"
        ]
        self.assertEqual(len(construction), 3)
        self.assertEqual(partition["continuity"]["link_count"], 2)
        self.assertTrue(partition["coordinate_validation"]["verified"])
        fragment_ids = []
        geometry_ids = []
        for zone in construction:
            self.assertEqual(zone["source_geometry_ids"], [7])
            self.assertEqual(zone["logical_objects"][0]["object_id"], "main-line")
            geometry = zone["geometries"][0]
            local_geometry = zone["local_geometries"][0]
            self.assertEqual(geometry["source_geometry_id"], 7)
            self.assertEqual(
                local_geometry["coordinate_frame"],
                zone["local_frame"]["frame_id"],
            )
            self.assertEqual(len(zone["execution_segments"]), 1)
            fragment_ids.append(geometry["partition_fragment_id"])
            geometry_ids.append(geometry["id"])
        self.assertEqual(fragment_ids, ["g7-f0001", "g7-f0002", "g7-f0003"])
        self.assertEqual(len(geometry_ids), len(set(geometry_ids)))

    def test_zone_status_progresses_without_skipping_active_zone(self) -> None:
        partition = build_spatial_partition(
            "variant-2",
            [
                {
                    "id": 1,
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "end": {"x": 100000.0, "y": 0.0, "z": 0.0},
                }
            ],
            [],
            {},
            {
                "requires_partitioning": True,
                "suggested_rows": 1,
                "suggested_columns": 2,
            },
        )

        first = next_partition_zone(partition)
        self.assertEqual(first["id"], "zone-r001-c001")
        planning = update_partition_zone(partition, first["id"], "planning")
        self.assertEqual(next_partition_zone(planning)["id"], first["id"])
        completed = update_partition_zone(planning, first["id"], "completed")
        self.assertEqual(completed["summary"]["completed_zone_count"], 1)
        self.assertEqual(completed["summary"]["progress"], 0.5)
        self.assertEqual(
            next_partition_zone(completed)["id"], "zone-r001-c002"
        )
        all_completed = update_partition_zone(
            completed, "zone-r001-c002", "completed"
        )
        self.assertTrue(all_completed["summary"]["all_completed"])
        self.assertIsNone(next_partition_zone(all_completed))

    def test_dense_zone_is_split_into_stable_execution_segments(self) -> None:
        geometries = [
            {
                "id": index,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0.0, "y": index * 10.0, "z": 0.0},
                "end": {"x": 1000.0, "y": index * 10.0, "z": 0.0},
            }
            for index in range(1, 206)
        ]
        partition = build_spatial_partition(
            "variant-dense",
            geometries,
            [],
            {},
            {
                "requires_partitioning": True,
                "suggested_rows": 1,
                "suggested_columns": 1,
            },
        )
        zone = next_partition_zone(partition)
        segments = zone["execution_segments"]

        self.assertEqual([len(item["geometry_ids"]) for item in segments], [100, 100, 5])
        self.assertEqual(
            [item["id"] for item in segments],
            [
                "zone-r001-c001-segment-0001",
                "zone-r001-c001-segment-0002",
                "zone-r001-c001-segment-0003",
            ],
        )
        self.assertEqual(
            partition["summary"]["execution_segment_count"], 3
        )
        first = next_partition_segment(zone)
        updated = update_partition_segment(
            partition, zone["id"], first["id"], "completed"
        )
        updated_zone = next_partition_zone(updated)
        self.assertEqual(
            next_partition_segment(updated_zone)["id"],
            "zone-r001-c001-segment-0002",
        )
        self.assertEqual(
            updated["summary"]["completed_execution_segment_count"], 1
        )


if __name__ == "__main__":
    unittest.main()
