# -*- coding: utf-8 -*-
from app.cad_structure_contract import explicit_composition
s='生成一个圆形和一个矩形，圆形在矩形上方；圆半径1米，圆心(0,3)；矩形左下角(-1,-1)，宽2米高2米，坐标单位米'
import pprint;pprint.pp(explicit_composition(s))
