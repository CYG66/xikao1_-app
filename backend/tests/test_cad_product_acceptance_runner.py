import json
from tests.manual.run_cad_product_acceptance import verify_recording


def test_recorded_inputs_must_match_frozen_corpus(tmp_path):
    case={"id":"one","messages":["生成一个圆","孔：圆，圆心(0,0)，半径1米，坐标单位米","确认生成"],
          "expected_preview_count":1,"expected_assemblies":1}
    objects=[{"object_id":"part","geometry_refs":[1],"assembly_id":"whole","assembly_label":"圆"}]
    (tmp_path/'ui-fixture.json').write_text(json.dumps(case),encoding='utf-8')
    variant={"id":"v","logical_objects":objects,"geometries":[{"id":1,"type":"circle","center":{"x":0,"y":0},"radius":1000}],
        "requirement_ledger":{"sources":[{"origin":"user","text":m} for m in case["messages"][:2]]}}
    for index,message in enumerate(case["messages"],1):
        (tmp_path/f'request-{index}.json').write_text(json.dumps({"message":message}),encoding='utf-8')
        response={"project_id":"p","ok":True}
        if index==1:response['clarification']={"question_key":"size"}
        if index==3:response.update(variant=variant,preview_paths=[{"geometry_id":1}],drawing_json={"logical_objects":objects})
        (tmp_path/f'step-{index}.json').write_text(json.dumps(response),encoding='utf-8')
    assert verify_recording(case,tmp_path)['passed']
    (tmp_path/'request-2.json').write_text(json.dumps({"message":"另一个不同的输入"}),encoding='utf-8')
    report=verify_recording(case,tmp_path)
    assert not report['passed']
    assert report['checks']['frozen_input_matches'] is False
    (tmp_path/'request-2.json').write_text(json.dumps({"message":case['messages'][1]}),encoding='utf-8')
    (tmp_path/'ui-fixture.json').write_text(json.dumps({**case,"expected_assemblies":None}),encoding='utf-8')
    report=verify_recording(case,tmp_path)
    assert not report['passed']
    assert report['checks']['ui_fixture_matches'] is False
