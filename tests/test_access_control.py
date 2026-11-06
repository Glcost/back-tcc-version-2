"""Actual API blueprints and JWTs, with fictitious students in two separate classes."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jwt
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth import gerar_token


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.columns, self.operation = [], '*', 'select'
        self.payload, self.single_row, self.maximum, self.sort = None, False, None, None

    def select(self, columns='*', **kwargs): self.columns=columns; return self
    def eq(self, key, value): self.filters.append((key,lambda item:item==value)); return self
    def neq(self, key, value): self.filters.append((key,lambda item:item!=value)); return self
    def in_(self, key, values): self.filters.append((key,lambda item:item in values)); return self
    def gt(self, key, value): self.filters.append((key,lambda item:item is not None and item>value)); return self
    def gte(self, key, value): self.filters.append((key,lambda item:item is not None and item>=value)); return self
    def lt(self, key, value): self.filters.append((key,lambda item:item is not None and item<value)); return self
    def lte(self, key, value): self.filters.append((key,lambda item:item is not None and item<=value)); return self
    def limit(self, value): self.maximum=value; return self
    def single(self): self.single_row=True; return self
    def maybe_single(self): self.single_row=True; return self
    def order(self, key, desc=False): self.sort=(key,desc); return self
    def insert(self, payload): self.operation,self.payload='insert',payload; return self
    def update(self, payload): self.operation,self.payload='update',payload; return self
    def delete(self): self.operation='delete'; return self
    def upsert(self, payload, **kwargs): self.operation,self.payload='upsert',payload; return self

    def execute(self):
        self.db.calls.append((self.table,self.operation))
        if self.db.fail_table == self.table:
            raise RuntimeError('private database connection and credential details')
        table = self.db.tables.setdefault(self.table,[])
        rows = [row for row in table if all(test(row.get(key)) for key,test in self.filters)]
        if self.operation in ('insert','upsert'):
            payloads = self.payload if isinstance(self.payload,list) else [self.payload]
            rows=[]
            for payload in payloads:
                item=deepcopy(payload)
                if self.operation=='insert': item.setdefault('id',max([row.get('id',0) for row in table]+[0])+1)
                if self.table=='alunos':
                    item.setdefault('ativo',True); item.setdefault('xp_total',0); item.setdefault('skin_ativa_id',1)
                table.append(item); rows.append(item)
        elif self.operation=='update':
            for row in rows: row.update(deepcopy(self.payload))
        elif self.operation=='delete':
            for row in rows: table.remove(row)
        count=len(rows)
        if self.sort:
            key,desc=self.sort
            rows=sorted(rows,key=lambda row:row.get(key) or '',reverse=desc)
        if self.maximum is not None: rows=rows[:self.maximum]
        if self.columns!='*':
            columns=[name.strip() for name in self.columns.split(',')]
            rows=[{name:row.get(name) for name in columns} for row in rows]
        else: rows=deepcopy(rows)
        if self.single_row and not rows:
            return None
        return SimpleNamespace(data=rows[0] if self.single_row else rows,count=count)


class Database:
    def __init__(self):
        self.tables,self.calls,self.rpcs,self.fail_table={},[],[],None

    def table(self, name): return Query(self,name)

    def rpc(self, name, args):
        self.rpcs.append((name,deepcopy(args)))
        if name=='roar_student_word_report': result={'palavras':[]}
        elif name=='roar_register_progress':
            result={'status':201,'data':{'aluno_id':args['p_aluno_id'],'atividade_id':args['p_atividade_id'],'xp_ganho':50}}
        elif name=='roar_shop_transaction': result={'status':200,'xp_atual':100}
        else: result=args.get('p_preferencias',{})
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=deepcopy(result)))


class AccessControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=Database()
        names=['src.bd_config','src.suporte_tea','src.learning_improvements','src.aluno','src.professora',
               'src.atividades','src.relatorios','src.privacidade','src.assistente_ia']
        previous={name:sys.modules.get(name) for name in names}
        for name in names: sys.modules.pop(name,None)
        replacements={'src.bd_config':SimpleNamespace(supabase=cls.db,supabase_admin=cls.db),
            'src.assistente_ia':SimpleNamespace(gerar_analise_aluno=lambda metrics:{},AssistenteIAIndisponivel=RuntimeError),
            'dotenv':SimpleNamespace(load_dotenv=lambda:False),
            'flasgger':SimpleNamespace(Swagger=lambda *args,**kwargs:None)}
        try:
            with patch.dict(sys.modules,replacements):
                spec=importlib.util.spec_from_file_location('tested_access_app',ROOT/'app.py')
                module=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cls.app=module.app
                cls.app.config.update(TESTING=True,SECRET_KEY='access-test-secret-with-at-least-32-characters')
                cls.modules={name:sys.modules[name] for name in names if name in sys.modules}
        finally:
            for name in names:
                if previous[name] is None: sys.modules.pop(name,None)
                else: sys.modules[name]=previous[name]
        cls.password_hash=generate_password_hash('test-only-password',method='pbkdf2:sha256:1000')

    def setUp(self):
        self.db.calls.clear(); self.db.rpcs.clear(); self.db.fail_table=None
        self.db.tables={
            'professores':[{'id':5,'nome':'Docente A','email':'teacher-a@example.invalid','senha':self.password_hash,'email_verificado_em':'2026-11-01'},
                           {'id':6,'nome':'Docente B','email':'teacher-b@example.invalid','senha':self.password_hash,'email_verificado_em':'2026-11-01'}],
            'alunos':[{'id':id,'professor_id':teacher,'nome':name,'email':f'student-{id}@example.invalid','ativo':active,
                'ano_escolar':'6º Ano','modo_aprendizagem':'Nível 2 - Aprendiz Guiado','pin_acesso':'1234','xp_total':100,'skin_ativa_id':1}
                for id,teacher,name,active in [(17,5,'Aluno A',True),(18,6,'Aluno B',True),(19,5,'Aluno inativo',False)]],
            'aluno_suporte_tea':[{'aluno_id':17,'nivel_suporte_tea':2},{'aluno_id':18,'nivel_suporte_tea':1}],
            'modulos':[{'id':9,'nome':'Módulo teste','ativo':True}],
            'atividades':[{'id':1,'modulo_id':9,'palavra_chave':'HEAD','ordem_sequencia':1}],
            'variacoes_atividades':[{'id':1,'atividade_id':1,'modo_alvo':'Nível 2 - Aprendiz Guiado',
                'instrucao_lex':'Observe HEAD','tipo_interacao':'Tap','resposta_correta':'HEAD','url_midia_padrao':'/fake.png'}],
            'itens_modulo':[{'id':51,'modulo_id':9,'palavra_en':'HEAD','palavra_pt':'Cabeça',
                'url_imagem_vetor':'/fake.svg','url_imagem_real':'/fake.png','ordem':1,'ativo':True}],
            'professor_modulos':[], 'personalizacao_aluno':[],
            'historico_desempenho':[{'id':id,'aluno_id':student,'atividade_id':1,'modo_utilizado':'Nível 2 - Aprendiz Guiado',
                'quantidade_erros':0,'tempo_segundos':10,'concluido':True,'data_hora':'2026-11-06T12:00:00Z'}
                for id,student in [(31,17),(32,18)]],
            'aluno_skins_lex':[], 'avaliacao_inicial':[], 'aluno_preferencias_jogos':[],
        }
        self.client=self.app.test_client()
        self.module_patch=patch.dict(sys.modules,self.modules)
        self.module_patch.start(); self.addCleanup(self.module_patch.stop)

    def headers(self, profile='professor', identifier=5):
        with self.app.app_context(): token=gerar_token({'id':identifier,'nome':'Teste'},perfil=profile)
        return {'Authorization':'Bearer '+token}

    def get(self, url, profile='professor', identifier=5):
        return self.client.get(url,headers=self.headers(profile,identifier))

    def test_every_personal_route_requires_authentication(self):
        public={'professores.cadastro_professor','professores.login_professor','alunos.login_aluno',
            'professores.solicitar_recuperacao_senha','professores.validar_codigo_recuperacao',
            'professores.redefinir_senha_professor','professores.confirmar_email_professor','professores.reenviar_codigo_email_professor'}
        checked=0
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith(('/professores/','/alunos/','/atividades/','/relatorios/')) or rule.endpoint in public:
                continue
            url=rule.rule
            for argument in rule.arguments: url=url.replace(f'<int:{argument}>','17')
            for method in rule.methods-{'HEAD','OPTIONS'}:
                with self.subTest(url=url,method=method):
                    response=self.client.open(url,method=method,json={})
                    self.assertEqual(response.status_code,401)
                    self.assertEqual(response.headers['Cache-Control'],'no-store, private')
                    checked+=1
        self.assertGreater(checked,25)
        self.assertEqual(self.db.calls,[])

    def test_teacher_and_student_logins_keep_existing_contract_without_returning_password_hash(self):
        teacher=self.client.post('/professores/login',json={'email':'teacher-a@example.invalid','senha':'test-only-password'})
        self.assertEqual(teacher.status_code,200)
        self.assertEqual(teacher.json['professor']['id'],5)
        self.assertNotIn(self.password_hash,teacher.text)
        student=self.client.post('/alunos/login',json={'email':'student-17@example.invalid','pin':'1234'})
        self.assertEqual(student.status_code,200)
        self.assertEqual(student.json['user']['id'],17)
        self.assertEqual(student.json['user']['teaSupportLevel'],2)
        self.assertEqual(student.headers['Cache-Control'],'no-store, private')

    def test_invalid_logins_do_not_issue_tokens_or_reveal_database_details(self):
        for url,body in [('/professores/login',{'email':'teacher-a@example.invalid','senha':'wrong'}),
                         ('/alunos/login',{'email':'student-17@example.invalid','pin':'0000'})]:
            response=self.client.post(url,json=body)
            self.assertEqual(response.status_code,401)
            self.assertNotIn('token',response.json)
        self.db.fail_table='alunos'
        response=self.client.post('/alunos/login',json={'email':'student-17@example.invalid','pin':'1234'})
        self.assertEqual(response.status_code,500)
        self.assertNotIn('private database',response.text)

    def test_teacher_only_lists_their_own_students_and_profile(self):
        own=self.get('/professores/aluno/professor/5')
        self.assertEqual(own.status_code,200)
        self.assertEqual([row['id'] for row in own.json],[17])
        for url in ['/professores/aluno/professor/6','/professores/perfil/6','/professores/dashboard/estatisticas/6',
                    '/relatorios/professor/6','/relatorios/visao-geral']:
            self.assertEqual(self.get(url).status_code,403,url)

    def test_teacher_cannot_read_edit_deactivate_reset_pin_or_export_another_class(self):
        before=deepcopy(self.db.tables)
        requests=[('GET','/professores/desempenho/aluno/18',None),('GET','/professores/alunos/perfil/18',None),
            ('GET','/relatorios/aluno/18',None),('GET','/relatorios/aluno/18/palavras',None),
            ('GET','/professores/alunos/18/preferencias-jogos',None),
            ('PUT','/professores/alunos/18',{'nome':'Alterado'}),('DELETE','/professores/alunos/18',None),
            ('PATCH','/professores/alunos/18/pin',{}),('PATCH','/professores/alunos/18/preferencias-jogos',{'pieceCount':2}),
            ('POST','/professores/alunos/18/exportacao-dados',{'solicitante':'titular','verificacao_confirmada':True}),
            ('POST','/professores/alunos/18/relatorio-dados.pdf',{'solicitante':'titular','verificacao_confirmada':True}),
            ('POST','/relatorios/aluno/18/analise-ia',{})]
        for method,url,body in requests:
            self.db.calls.clear()
            response=self.client.open(url,method=method,json=body,headers=self.headers())
            self.assertEqual(response.status_code,403,url)
            self.assertFalse(any(table in ('historico_desempenho','aluno_suporte_tea','avaliacao_inicial') for table,op in self.db.calls),url)
        self.assertEqual(self.db.tables,before)
        self.assertEqual(self.db.rpcs,[])

    def test_student_cannot_read_another_student_or_use_teacher_actions(self):
        for url in ['/alunos/perfil/18','/atividades/modulo/9/aluno/18','/relatorios/aluno/18',
                    '/relatorios/aluno/18/palavras','/professores/aluno/professor/5','/professores/alunos/perfil/17']:
            self.assertEqual(self.get(url,'aluno',17).status_code,403,url)
        for suffix in ['exportacao-dados','relatorio-dados.pdf']:
            response=self.client.post('/professores/alunos/17/'+suffix,headers=self.headers('aluno',17),
                json={'solicitante':'titular','verificacao_confirmada':True})
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.db.rpcs,[])

    def test_own_reports_and_activity_payload_stay_available(self):
        for url,profile,identifier in [('/professores/alunos/perfil/17','professor',5),
            ('/professores/desempenho/aluno/17','professor',5),('/relatorios/aluno/17','professor',5),
            ('/relatorios/professor/5','professor',5),('/alunos/me','aluno',17),
            ('/alunos/perfil/17','aluno',17),('/atividades/modulo/9/aluno/17','aluno',17),
            ('/alunos/preferencias-jogos','aluno',17),('/relatorios/aluno/17','aluno',17)]:
            response=self.get(url,profile,identifier)
            self.assertEqual(response.status_code,200,(url,response.json))
            self.assertNotIn('Aluno B',response.text)
            self.assertNotIn('student-18@example.invalid',response.text)

    def test_inactive_student_cannot_login_or_retrieve_gameplay_and_reports(self):
        response=self.client.post('/alunos/login',json={'email':'student-19@example.invalid','pin':'1234'})
        self.assertEqual(response.status_code,401)
        for url in ['/alunos/me','/alunos/perfil/19','/atividades/modulo/9/aluno/19','/relatorios/aluno/19','/alunos/preferencias-jogos']:
            self.assertIn(self.get(url,'aluno',19).status_code,(403,404),url)

    def test_both_progress_urls_reject_identity_tampering_without_writing(self):
        before=deepcopy(self.db.tables)
        for url in ['/alunos/desempenho','/atividades/progresso']:
            response=self.client.post(url,headers=self.headers('aluno',17),json={'aluno_id':18,'atividade_id':1})
            self.assertEqual(response.status_code,403)
            response=self.client.post(url,headers=self.headers(),json={'aluno_id':17,'atividade_id':1})
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.db.rpcs,[])
        self.assertEqual(self.db.tables,before)

    def test_legacy_progress_uses_authenticated_identity_and_registered_learning_mode(self):
        response=self.client.post('/alunos/desempenho',headers=self.headers('aluno',17),json={
            'atividade_id':1,'modo_utilizado':'forged','quantidade_erros':0,'tempo_segundos':10,
            'concluido':True,'id_tentativa':'00000000-0000-4000-8000-000000000001'})
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(self.db.rpcs[-1][0],'roar_register_progress')
        self.assertEqual(self.db.rpcs[-1][1]['p_aluno_id'],17)
        self.assertEqual(self.db.rpcs[-1][1]['p_atividade_id'],1)

    def test_invalid_or_unbounded_tokens_never_reach_database(self):
        now=datetime.now(timezone.utc)
        claims={'sub':'17','perfil':'aluno','iat':now,'exp':now+timedelta(minutes=5)}
        for overrides in [{'exp':None},{'sub':'-17'},{'sub':'0'},{'perfil':'admin'},{'exp':now-timedelta(minutes=1)}]:
            payload={**claims,**overrides}
            if payload.get('exp') is None: payload.pop('exp')
            token=jwt.encode(payload,self.app.config['SECRET_KEY'],algorithm='HS256')
            response=self.client.get('/alunos/me',headers={'Authorization':'Bearer '+token})
            self.assertEqual(response.status_code,401)
        self.assertEqual(self.db.calls,[])


class DatabaseConfigurationTests(unittest.TestCase):
    def import_config(self, values):
        calls=[]
        marker=object()
        spec=importlib.util.spec_from_file_location('tested_private_db',ROOT/'src/bd_config.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict('os.environ',values,clear=True), patch.dict(sys.modules,{
            'dotenv':SimpleNamespace(load_dotenv=lambda:False),
            'supabase':SimpleNamespace(Client=object,create_client=lambda url,key:(calls.append((url,key)) or marker)),
        }): spec.loader.exec_module(module)
        return module,calls,marker

    def test_private_client_is_used_for_every_server_alias(self):
        module,calls,marker=self.import_config({'SUPABASE_URL':'https://example.invalid',
            'SUPABASE_SECRET_KEY':'sb_secret_test-only','SUPABASE_KEY':'sb_publishable_ignored'})
        self.assertIs(module.supabase,marker)
        self.assertIs(module.supabase_admin,marker)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],'sb_secret_test-only')

    def test_missing_or_public_keys_fail_closed_without_including_them_in_errors(self):
        for value in ['', 'sb_publishable_test-only', 'invalid-key']:
            with self.assertRaises(EnvironmentError) as caught:
                self.import_config({'SUPABASE_URL':'https://example.invalid','SUPABASE_SECRET_KEY':value,'SUPABASE_KEY':'ignored-public'})
            self.assertNotIn('test-only',str(caught.exception))
            self.assertNotIn('invalid-key',str(caught.exception))

    def test_legacy_service_role_is_accepted_and_anon_is_rejected(self):
        for role in ['service_role','anon']:
            payload=base64.urlsafe_b64encode(('{"role":"'+role+'"}').encode()).decode().rstrip('=')
            key='header.'+payload+'.signature'
            values={'SUPABASE_URL':'https://example.invalid','SUPABASE_SECRET_KEY':key}
            if role=='service_role': self.assertEqual(len(self.import_config(values)[1]),1)
            else:
                with self.assertRaises(EnvironmentError): self.import_config(values)


if __name__=='__main__': unittest.main()
