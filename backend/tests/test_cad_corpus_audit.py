import json
from tests.manual.audit_cad_corpus_run import audit


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def test_candidate_or_clarification_is_not_promoted_to_a_pass(tmp_path):
    write(tmp_path/'manifest.json',{'requested':['B1','C6','C17']})
    write(tmp_path/'B1/corpus-report.json',{'case':'B1','kind':'edit','has_candidate':True,
        'checks':[{'name':'new_saved_version','passed':False}]})
    write(tmp_path/'B1/step-1.json',{'pending_action':{'id':'pending'},
        'execution_plan':{'status':'completed'}})
    write(tmp_path/'C17/corpus-report.json',{'case':'C17','has_candidate':True,
        'checks':[{'name':'honeycomb_shared_edges_review','passed':False}]})
    report=audit(tmp_path)
    assert not report['complete']
    assert report['outcomes']=={'edit_not_saved_or_clarification':1,'requires_review':1}
    assert report['trace_conflict_cases']==['B1']


def test_auxiliary_followup_does_not_double_count_original_case(tmp_path):
    write(tmp_path/'manifest.json',{'requested':['D2']})
    record={'case':'D2','kind':'edit','has_candidate':False,'checks':[]}
    write(tmp_path/'D2/corpus-report.json',record)
    write(tmp_path/'D2-followup/corpus-report.json',record)
    report=audit(tmp_path)
    assert report['completed_cases']==report['requested_cases']==1
    assert report['auxiliary_report_paths']
