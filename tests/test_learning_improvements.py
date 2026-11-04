"""Real Flask/JWT route tests, using in-memory database adapters only."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, Blueprint, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth import token_obrigatorio, gerar_token


class Query:
    def __init__(self, database, table):
        self.database, self.table, self.filters = database, table, {}
    def select(self, *args): return self
    def eq(self, key, value): self.filters[key] = value; return self
    def limit(self, *args): return self
    def execute(self):
        self.database.reads.append((self.table, self.filters.copy()))
        if self.table == 'alunos':
            if self.filters.get('id') != 17 or self.filters.get('professor_id', 5) != 5:
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[{'id':17}])
        if self.table == 'aluno_preferencias_jogos':
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[{'id':1}])


class Database:
    def __init__(self):
        self.reads, self.calls = [], []
        self.response, self.fail = {}, False
    def table(self, name): return Query(self, name)
    def rpc(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail: raise RuntimeError('private database detail')
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=self.response.copy()))


def production_functions(filename, names, namespace, *, decorators=True):
    tree = ast.parse((ROOT/'src'/filename).read_text(encoding='utf-8-sig'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in selected:
        if not decorators: node.decorator_list=[]
    exec(compile(ast.Module(body=selected,type_ignores=[]),filename,'exec'),namespace)
    return namespace


class LearningRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import actual route code without initializing a Supabase client/network.
        spec = importlib.util.spec_from_file_location('src.learning_improvements',ROOT/'src/learning_improvements.py')
        cls.learning=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'src.bd_config':SimpleNamespace(supabase_admin=None)}):
            spec.loader.exec_module(cls.learning)
        cls.app=Flask(__name__)
        cls.app.config.update(TESTING=True,SECRET_KEY='test-only-secret-with-at-least-32-characters')
        cls.app.register_blueprint(cls.learning.learning_bp)
        cls.database=Database()
        cls.activity_namespace=production_functions('atividades.py',[
            'resposta_erro','converter_inteiro','converter_booleano','obter_aluno_autenticado','registrar_progresso',
        ], {'atividades_bp':Blueprint('tested_activities',__name__),
            'token_obrigatorio':token_obrigatorio,'request':request,'jsonify':jsonify,
            'MAXIMO_ERROS':1000,'MAXIMO_TEMPO_SEGUNDOS':86400,
            'MODOS_APRENDIZAGEM':{'Nível 1 - Suporte Visual Puro'},
            'buscar_aluno':lambda student_id:{'id':student_id,'modo_aprendizagem':'Nível 1 - Suporte Visual Puro'},
            'normalize_word_evidence':cls.learning.normalize_word_evidence,
            'normalize_attempt_id':cls.learning.normalize_attempt_id,
            'atomic_operation':cls.learning.atomic_operation,
            'LearningUnavailable':cls.learning.LearningUnavailable,
            'unavailable_response':cls.learning.unavailable_response,
        })
        cls.app.register_blueprint(cls.activity_namespace['atividades_bp'],url_prefix='/atividades')
        cls.student_namespace=production_functions('aluno.py',['salvar_desempenho','loja_lex'],{
            'alunos_bp':Blueprint('tested_students',__name__),'token_obrigatorio':token_obrigatorio,
            'request':request,'jsonify':jsonify,
        })
        cls.app.register_blueprint(cls.student_namespace['alunos_bp'],url_prefix='/alunos')

    def setUp(self):
        self.database=Database()
        self.learning.supabase_admin=self.database
        self.activity_namespace['supabase']=self.database
        self.client=self.app.test_client()
        self.module_patches=patch.dict(sys.modules,{
            'src.learning_improvements':self.learning,
            'src.atividades':SimpleNamespace(registrar_progresso=self.activity_namespace['registrar_progresso']),
        })
        self.module_patches.start()
        self.addCleanup(self.module_patches.stop)

    def headers(self, profile='aluno',identifier=17):
        with self.app.app_context(): token=gerar_token({'id':identifier,'nome':'Teste'},perfil=profile)
        return {'Authorization':'Bearer '+token}

    def test_all_new_routes_require_a_token(self):
        for method,url in [('get','/alunos/preferencias-jogos'),('get','/professores/alunos/17/preferencias-jogos'),
            ('patch','/professores/alunos/17/preferencias-jogos'),('get','/relatorios/aluno/17/palavras'),
            ('post','/alunos/desempenho'),('post','/alunos/loja-lex'),('post','/atividades/progresso')]:
            with self.subTest(url=url): self.assertEqual(getattr(self.client,method)(url,json={}).status_code,401)
        self.assertEqual(self.database.calls,[])
        self.assertEqual(self.database.reads,[])

    def test_teacher_only_changes_owned_students(self):
        for profile,identifier in [('aluno',17),('professor',6)]:
            result=self.client.patch('/professores/alunos/17/preferencias-jogos',headers=self.headers(profile,identifier),json={'pieceCount':2})
            self.assertEqual(result.status_code,403)
        self.assertEqual(self.database.calls,[])
        self.database.response={'pieceCount':2,'showHints':True,'memoryPreviewSeconds':5,'advanceDelaySeconds':1}
        result=self.client.patch('/professores/alunos/17/preferencias-jogos',headers=self.headers('professor',5),json={'pieceCount':2})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.database.calls[0],('roar_save_game_preferences',{'p_aluno_id':17,'p_professor_id':5,'p_preferencias':{'pieceCount':2}}))

    def test_missing_preferences_returns_documented_defaults(self):
        result=self.client.get('/alunos/preferencias-jogos',headers=self.headers())
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json,self.learning.DEFAULT_GAME_PREFERENCES)

    def test_invalid_preferences_do_not_write(self):
        for data in ({'pieceCount':True},{'pieceCount':3},{'memoryPreviewSeconds':0},{'advanceDelaySeconds':'1'},{'showHints':1},{'other':1}):
            result=self.client.patch('/professores/alunos/17/preferencias-jogos',headers=self.headers('professor',5),json=data)
            self.assertEqual(result.status_code,400)
        self.assertEqual(self.database.calls,[])

    def test_reports_deny_other_student_and_other_teacher(self):
        for profile,identifier in [('aluno',18),('professor',6)]:
            result=self.client.get('/relatorios/aluno/17/palavras',headers=self.headers(profile,identifier))
            self.assertEqual(result.status_code,403)
        self.assertEqual(self.database.calls,[])
        self.database.response={'palavras':[{'palavra':'HEAD','acertos':1,'erros':0,'ajudas':0}]}
        result=self.client.get('/relatorios/aluno/17/palavras',headers=self.headers('professor',5))
        self.assertEqual(result.json['palavras'][0]['palavra'],'HEAD')

    def test_missing_database_fails_closed_without_leaking_details(self):
        self.learning.supabase_admin=None
        result=self.client.get('/alunos/preferencias-jogos',headers=self.headers())
        self.assertEqual(result.status_code,503)
        self.database.fail=True
        self.learning.supabase_admin=self.database
        result=self.client.post('/alunos/loja-lex',headers=self.headers(),json={'acao':'comprar','skin_id':2})
        self.assertEqual(result.status_code,503)
        self.assertNotIn('private database detail',result.get_data(as_text=True))

    def test_readiness_never_uses_student_data_or_leaks_configuration(self):
        self.database.response={'palavras':[]}
        result=self.client.get('/health/learning')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json,{'status':'ready'})
        self.assertEqual(self.database.calls,[('roar_student_word_report',{'p_aluno_id':-1})])
        self.assertEqual(self.database.reads,[])
        self.learning.supabase_admin=None
        result=self.client.get('/health/learning')
        self.assertEqual(result.status_code,503)
        self.assertEqual(result.json,{'status':'unavailable'})

    def test_shop_uses_token_identity_and_rejects_invalid_ids(self):
        for data in ({'acao':'equipar','skin_id':True},{'acao':'comprar','skin_id':-1},{'acao':'other','skin_id':2}):
            result=self.client.post('/alunos/loja-lex',headers=self.headers(),json=data)
            self.assertEqual(result.status_code,400)
        self.assertEqual(self.database.calls,[])
        self.database.response={'xp_restante':400,'status':200}
        result=self.client.post('/alunos/loja-lex',headers=self.headers(),json={'aluno_id':99,'acao':'comprar','skin_id':2})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.database.calls[0][1]['p_aluno_id'],17)

    def test_legacy_progress_denies_another_student(self):
        result=self.client.post('/alunos/desempenho',headers=self.headers(),json={'aluno_id':99,'atividade_id':1})
        self.assertEqual(result.status_code,403)
        self.assertEqual(self.database.calls,[])

    def test_progress_validates_evidence_and_uuid_before_rpc(self):
        for extra in ({'palavras':[{'palavra':'HEAD','acertos':True}]},{'palavras':'HEAD'},{'id_tentativa':'not-a-uuid'}):
            result=self.client.post('/atividades/progresso',headers=self.headers(),json={'atividade_id':1,**extra})
            self.assertEqual(result.status_code,400)
        self.assertEqual(self.database.calls,[])

    def test_progress_delegates_history_reward_and_evidence_to_one_transaction(self):
        attempt='00000000-0000-4000-8000-000000000001'
        self.database.response={'data':{'xp_ganho':50},'status':201}
        result=self.client.post('/alunos/desempenho',headers=self.headers(),json={
            'atividade_id':1,'id_tentativa':attempt,'quantidade_erros':0,'tempo_segundos':10,
            'palavras':[{'palavra':' head ','acertos':1,'erros':0,'ajudas':1}],
        })
        self.assertEqual(result.status_code,201)
        name,args=self.database.calls[0]
        self.assertEqual(name,'roar_register_progress')
        self.assertEqual(args['p_id_tentativa'],attempt)
        self.assertEqual(args['p_palavras'][0]['palavra'],'HEAD')
        self.assertEqual(args['p_aluno_id'],17)


if __name__=='__main__': unittest.main()
