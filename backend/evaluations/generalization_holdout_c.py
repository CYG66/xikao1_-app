"""Third internal holdout, authored after production freeze; never repair in run."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from scripts.local_dev import ROOT
from evaluations import transfer_holdout_20261124 as run
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle
from evaluations.relation_pilot.cases import expected_entities

FREEZE = ROOT / '.local-dev/generalization-c-freeze-ruc6e9gu'


def cases():
    points = [{'x': -430, 'y': 710}]
    for length, angle in [(1280, 18), (760, -43), (940, 30), (580, -16), (1110, 45)]:
        p = points[-1]; a = math.radians(angle)
        points.append({'x': p['x'] + length * math.cos(a), 'y': p['y'] + length * math.sin(a)})
    return [
        {'id': 'V1', 'category': 'concentric_different_radii', 'family': 'explicit_geometry',
         'expected': [{'type': 'circle', 'center': {'x': 740, 'y': -1260}, 'radius': r} for r in (860, 320)],
         'text': '画两个同心圆，共用圆心(0.74,-1.26)，外圆半径0.86米，内圆半径0.32米。仅保留两个圆的轮廓，不加任何标注。坐标单位米。'},
        {'id': 'V2', 'category': 'five_vertex_polygon', 'family': 'explicit_geometry',
         'expected': [{'type': 'polyline', 'closed': True, 'vertices': [{'x': x, 'y': y} for x,y in [(-780,-120),(460,-390),(1190,350),(530,1430),(-690,910)]]}],
         'text': '依次连接顶点(-78,-12)、(46,-39)、(119,35)、(53,143)、(-69,91)，最后连接回第一个顶点，形成一个闭合五边形。坐标单位厘米。'},
        {'id': 'V3', 'category': 'rotated_capsule_transfer', 'family': 'capsule_tangency',
         'unit': '厘米', 'origin': [-93.7, 118.6], 'length': 547, 'height': 138, 'angle': -47,
         'text': '绘制胶囊形闭合边界，中心位于(-93.7,118.6)，长轴相对x轴正向逆时针-47度，沿长轴总长547厘米、短轴总高138厘米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位厘米。'},
        {'id': 'V4', 'category': 'five_segment_mixed_units', 'family': 'explicit_geometry',
         'expected': [{'type': 'polyline', 'closed': False, 'vertices': points}],
         'text': '从(-43,71)出发画折线，先沿与x轴正向成18度的方向走1.28米，再向右转61度接着画760毫米，再向左转73度接着画94厘米，再向右转46度接着画0.58米，再向左转61度接着画111厘米。五段连续连接，末端不连回起点，不加其他图形。坐标单位厘米。'},
        {'id': 'V5', 'category': 'independent_named_combination', 'family': 'explicit_geometry',
         'expected': [
             {'type': 'line', 'start': {'x': -2100, 'y': 1630}, 'end': {'x': 1650, 'y': 1630}},
             {'type': 'polyline', 'closed': True, 'vertices': [{'x': x, 'y': y} for x,y in [(-560,-950),(710,-950),(710,-210),(-560,-210)]]},
             {'type': 'circle', 'center': {'x': 1890, 'y': -420}, 'radius': 365}],
         'text': '在同一张图中画三个独立图形。上横线：线段，起点(-2100,1630)，终点(1650,1630)，坐标单位毫米；下矩形：矩形，左下角(-560,-950)，宽1270毫米，高740毫米，坐标单位毫米；右圆：圆，圆心(1890,-420)，半径365毫米，坐标单位毫米。不要增加连接线或标注。'},
        {'id': 'V6', 'category': 'arch_paraphrase_transfer', 'family': 'semicircle_walls',
         'unit': '米', 'origin': [-1.36, -.72], 'width': 3.26, 'height': 4.61, 'angle': 0,
         'text': '画一个半圆拱门的闭合外轮廓。水平底边左端在(-1.36,-0.72)，整体宽3.26米，从底边到拱顶的整体高4.61米；左右两段直墙竖直且等高，顶上用直径3.26米的上半圆连接，整体高度包含这段半圆。不要内部线。坐标单位米。'},
    ]


def self_check():
    records = []
    def shift(obj):
        if isinstance(obj, list): return [shift(v) for v in obj]
        if isinstance(obj, dict): return {k: (v+20 if k == 'x' else shift(v)) for k,v in obj.items()}
        return obj
    for row in cases():
        gold = deepcopy(row['expected']) if 'expected' in row else expected_entities(row)
        assert holdout_oracle(row, gold)['passed']
        assert not holdout_oracle(row, shift(gold))['passed']
        try:
            assert not holdout_oracle(row, [])['passed']
        except ValueError as exc:
            assert str(exc) == 'empty_geometry'
        records.append({'case': row['id'], 'golden_passed': True, 'shifted_20mm_rejected': True, 'empty_rejected': True})
    base.dump(FREEZE / 'oracle-self-check.json', records)


def main():
    self_check()
    original_dump = base.dump
    def dump(path, value):
        if path.name == 'holdout-manifest.json':
            value = {**value, 'scope': 'Third new developer-authored internal holdout V1-V6, authored after source freeze; not third-party blind testing.'}
            value['hashes'].pop('docs/TRANSFER_HOLDOUT_PROTOCOL_20261124.md', None)
            for name in ['evaluations/generalization_holdout_c.py', 'docs/GENERALIZATION_C_PROTOCOL_20261124.md']:
                value['hashes'][name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        original_dump(path, value)
    base.dump = dump
    run.FREEZE = FREEZE
    run.cases = cases
    run.main()


if __name__ == '__main__': main()
