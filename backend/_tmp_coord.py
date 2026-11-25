# -*- coding: utf-8 -*-
from app.cad_coordinate_requirements import coordinate_scale
from app.cad_construction_interpreter import clarify_construction_request
s='画一条线段从(0,0)到(5,3)，坐标单位米'
print(coordinate_scale(s))
