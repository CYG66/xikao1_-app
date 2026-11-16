from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import projects


def test_manual_review_http_requires_owner_and_keeps_machine_evidence(monkeypatch):
    class Store:
        def get(self,p):return {'owner_conversation_id':'chat'}
        def record_manual_cad_confirmation(self,p,v,h,e):
            if h!='expected':raise ValueError('几何已变化')
            return {'project_id':p,'variant_id':v,'geometry_hash':h,'event_id':e,'construction_authorized':False}
    monkeypatch.setattr(projects,'get_creative_project_store',lambda:Store())
    app=FastAPI();app.include_router(projects.router)
    with TestClient(app) as client:
        url='/api/agent/projects/p/variants/v/manual-review'
        assert not client.post(url,json={'geometry_hash':'expected','event_id':'e'}).json()['ok']
        body={'conversation_id':'chat','geometry_hash':'bad','event_id':'e'}
        assert not client.post(url,json=body).json()['ok']
        body['geometry_hash']='expected'
        result=client.post(url,json=body).json()
        assert result['ok'] and not result['construction_authorized']
        assert 'acceptance_summary' not in result
