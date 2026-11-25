# -*- coding: utf-8 -*-
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore
with TemporaryDirectory() as d:
 s=CreativeProjectStore(Path(d)/'projects.json');svc=RobotAgentService(restore_pending_actions=False);svc.mode='local'
 route={'name':'drawing_design','operation':'create','decision_source':'test','clarification_required':False}
 with patch('app.agent_service.get_creative_project_store',return_value=s):
  r=svc._chat_impl('画一条线段从(0,0)到(5,3)，坐标单位米',[],mode='advanced',route=route)
 print(r)
