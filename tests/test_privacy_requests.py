from copy import deepcopy
import unittest

import test_access_control as access_tests


class PrivacyRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        access_tests.AccessControlTests.setUpClass.__func__(cls)

    setUp = access_tests.AccessControlTests.setUp
    headers = access_tests.AccessControlTests.headers
    get = access_tests.AccessControlTests.get

    def configure(self, enabled=True):
        self.app.config.update(ROAR_PRIVACY_REQUESTS_ENABLED='true' if enabled else 'false',
            ROAR_PRIVACY_CONTROLLER='Instituição de teste', ROAR_PRIVACY_CONTACT='teste@example.invalid')

    def body(self, **changes):
        return {'id':'00000000-0000-4000-8000-000000000001','tipo':'correcao',
            'descricao':'Corrigir o ano escolar cadastrado.','solicitante':'responsavel',
            'verificacao_confirmada':True, **changes}

    def create(self, student=17, teacher=5, **changes):
        return self.client.post(f'/professores/alunos/{student}/solicitacoes-dados',
            headers=self.headers('professor',teacher),json=self.body(**changes))

    def update(self, **body):
        return self.client.patch('/professores/alunos/17/solicitacoes-dados/'+self.body()['id'],
            headers=self.headers(),json=body)

    def test_intake_requires_explicit_configuration_but_tracking_remains_available(self):
        self.configure(False)
        self.assertEqual(self.get('/privacidade/atendimento').json,
            {'disponivel':False,'responsavel':None,'contato':None})
        self.assertEqual(self.create().status_code,503)
        self.assertEqual(self.get('/alunos/solicitacoes-dados','aluno',17).json['solicitacoes'],[])
        self.configure()
        self.app.config['ROAR_PRIVACY_CONTACT']=''
        self.assertEqual(self.create().status_code,503)
        self.assertEqual(self.get('/privacidade/atendimento').json['disponivel'],False)
        self.assertEqual(self.db.tables.get('solicitacoes_dados',[]),[])

    def test_owner_can_register_once_and_repeated_request_does_not_duplicate(self):
        self.configure()
        created=self.create()
        self.assertEqual(created.status_code,201,created.json)
        repeated=self.create()
        self.assertEqual(repeated.status_code,200,repeated.json)
        self.assertEqual(len(self.db.tables['solicitacoes_dados']),1)
        self.assertEqual(repeated.json['solicitacao']['protocolo'],'ROAR-'+self.body()['id'].upper())
        self.assertEqual(self.create(descricao='Uma descrição diferente.').status_code,409)
        self.assertEqual(self.db.tables['solicitacoes_dados'][0]['descricao'],self.body()['descricao'])

    def test_class_and_role_boundaries_are_checked_before_request_storage(self):
        self.configure()
        for method,url,profile,identifier in [
            ('GET','/professores/alunos/18/solicitacoes-dados','professor',5),
            ('POST','/professores/alunos/18/solicitacoes-dados','professor',5),
            ('GET','/professores/alunos/17/solicitacoes-dados','aluno',17),
            ('POST','/professores/alunos/17/solicitacoes-dados','aluno',17),
            ('GET','/alunos/solicitacoes-dados','professor',5),
            ('GET','/alunos/solicitacoes-dados','aluno',19),
            ('PATCH','/professores/alunos/18/solicitacoes-dados/'+self.body()['id'],'professor',5)]:
            self.db.calls.clear()
            response=self.client.open(url,method=method,json=self.body(),headers=self.headers(profile,identifier))
            self.assertEqual(response.status_code,403,(url,response.json))
            self.assertFalse(any(table.startswith('solicitacoes_dados') for table,operation in self.db.calls))

    def test_invalid_input_cannot_inject_owner_status_or_skip_verification(self):
        self.configure()
        for changes in [{'verificacao_confirmada':1},{'verificacao_confirmada':False},{'tipo':'exportacao'},
            {'descricao':'curta'},{'descricao':'x'*2001},{'descricao':7},{'id':'invalid'},
            {'professor_abertura_id':6},{'status':'respondida'},{'solicitante':'outro'}]:
            self.assertEqual(self.create(**changes).status_code,400,changes)
        self.assertNotIn('solicitacoes_dados',self.db.tables)

    def test_only_own_requests_and_events_are_returned_with_pagination(self):
        self.configure()
        template={**self.body(),'aluno_id':17,'ordem':1,'professor_abertura_id':5,
            'atendido_por_id':5,'status':'recebida','resposta':'','versao':1}
        self.db.tables['solicitacoes_dados']=[{**template,'id':f'00000000-0000-4000-8000-{i:012}','ordem':i} for i in range(1,54)]
        foreign={**template,'id':'00000000-0000-4000-8000-000000000099','aluno_id':18,'ordem':99}
        self.db.tables['solicitacoes_dados'].append(foreign)
        self.db.tables['solicitacoes_dados_eventos']=[{'id':1,'solicitacao_id':template['id'],'nome_professor':'Docente A'},
            {'id':2,'solicitacao_id':foreign['id'],'nome_professor':'Docente B'}]
        first=self.get('/alunos/solicitacoes-dados','aluno',17)
        self.assertEqual(len(first.json['solicitacoes']),50)
        self.assertEqual(first.json['proximo_cursor'],4)
        self.assertNotIn('Docente B',first.text)
        last=self.get('/professores/alunos/17/solicitacoes-dados?antes=4')
        self.assertEqual(len(last.json['solicitacoes']),3)
        self.assertEqual(last.json['solicitacoes'][-1]['eventos'][0]['nome_professor'],'Docente A')
        for suffix in ['?antes=-1','?antes=0','?antes=oops','?aluno_id=18']:
            self.assertEqual(self.get('/alunos/solicitacoes-dados'+suffix,'aluno',17).status_code,400)

    def test_response_is_versioned_final_and_does_not_change_student_data(self):
        self.configure()
        before=deepcopy(self.db.tables['alunos'])
        self.create()
        self.assertEqual(self.update(status='em_analise',resposta='',versao=1).status_code,200)
        self.assertEqual(self.update(status='respondida',resposta='Ano escolar corrigido.',versao=1).status_code,409)
        for body in [{'status':'respondida','resposta':'curta','versao':2},
                     {'status':'respondida','resposta':'Resposta válida.','versao':True},
                     {'status':'recebida','resposta':'','versao':2}]:
            self.assertEqual(self.update(**body).status_code,400)
        self.assertEqual(self.update(status='respondida',resposta='Ano escolar corrigido.',versao=2).status_code,200)
        self.assertEqual(self.update(status='em_analise',resposta='',versao=3).status_code,409)
        self.assertEqual(self.db.tables['alunos'],before)

    def test_failures_do_not_reveal_internal_details(self):
        self.configure()
        self.db.fail_table='solicitacoes_dados'
        response=self.get('/professores/alunos/17/solicitacoes-dados')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private database',response.text)
        self.assertEqual(response.headers['Cache-Control'],'no-store, private')


if __name__=='__main__': unittest.main()
