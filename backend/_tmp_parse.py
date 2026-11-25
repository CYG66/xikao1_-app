# -*- coding: utf-8 -*-
from app.cad_construction_interpreter import parse_rule_construction_plan, clarify_construction_request, interpret_construction_request
s='画一条线段从(0,0)到(5,3)，坐标单位米'
print(parse_rule_construction_plan(s))
print(clarify_construction_request(s))
print(interpret_construction_request(s).get('status'),interpret_construction_request(s).get('error'))
