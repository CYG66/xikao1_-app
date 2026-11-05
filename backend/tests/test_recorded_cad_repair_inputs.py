import json
import pytest
from tests.manual.run_recorded_cad_repair import recorded_response


def test_recorded_selector_preserves_legacy_low_confidence_and_explicit_failure_selection(tmp_path):
    def payload(confidence, label):
        return {'schema_version':'cad.construction-interpretation.v1','plan':{'label':label},'confidence':confidence}
    rows=[{'step':3,'response':json.dumps(payload(.72,'legacy'))},
          {'step':1,'response':json.dumps(payload(.9,'first'))},
          {'step':1,'response':json.dumps(payload(.85,'failed-feet'))}]
    (tmp_path/'model-responses.jsonl').write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
    assert recorded_response(tmp_path)['plan']['label']=='legacy'
    assert recorded_response(tmp_path,step=1,index=2)['plan']['label']=='failed-feet'
    with pytest.raises(ValueError,match='out of range'):recorded_response(tmp_path,step=1,index=3)
