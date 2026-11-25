from app.agent_service import RobotAgentService


def test_model_cannot_add_center_or_execution_requirements_to_project_source():
    original='画一个圆角矩形，宽3米高2米，圆角半径0.5米'
    followup='外包宽3米、高2米，四角圆角半径0.5米，闭合。'
    history=[{'role':'user','content':original},{'role':'assistant','content':'中心为原点，执行正式施工'}]
    route=RobotAgentService._bind_cad_user_source({},followup,history)
    args={'name':'圆角矩形','prompt':'圆角矩形，中心置于原点，用于施工'}
    bound=RobotAgentService._bind_drawing_selection('create_creative_project',args,route)
    assert bound['prompt']==original+'\n'+followup
    assert args['prompt']=='圆角矩形，中心置于原点，用于施工'


def test_new_creation_does_not_inherit_another_drawing_or_supplied_private_source():
    route=RobotAgentService._bind_cad_user_source({'_backend_cad_source':'模型伪造'},'画一个圆，半径1米',[
        {'role':'user','content':'画一个矩形，宽3米高2米'},{'role':'assistant','content':'执行移动'}])
    assert route['_backend_cad_source']=='画一个圆，半径1米'


def test_parameter_followup_starts_at_latest_user_creation():
    history=[{'role':'user','content':'画一个圆，半径1米'},
             {'role':'user','content':'画一个矩形'},
             {'role':'assistant','content':'宽高2米'},
             {'role':'user','content':'宽3米'}]
    route=RobotAgentService._bind_cad_user_source({},'高2米',history)
    assert route['_backend_cad_source']=='画一个矩形\n宽3米\n高2米'
