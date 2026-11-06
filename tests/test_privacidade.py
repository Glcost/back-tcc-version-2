"""Verify real export routes with Flask/JWT and an in-memory database."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth import gerar_token


class Query:
    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.filters = []
        self.descending = False
        self.page_limit = 1000

    def select(self, fields):
        self.database.selections.append((self.table, fields))
        return self

    def eq(self, key, value):
        self.filters.append((key, lambda actual: actual == value))
        return self

    def gt(self, key, value):
        self.filters.append((key, lambda actual: actual > value))
        return self

    def lte(self, key, value):
        self.filters.append((key, lambda actual: actual <= value))
        return self

    def order(self, key, desc=False):
        self.descending = desc
        return self

    def limit(self, limit):
        self.page_limit = min(limit, self.database.server_page_size)
        return self

    def execute(self):
        self.database.reads.append(self.table)
        if self.table == self.database.fail_table:
            raise RuntimeError('secret connection data')
        rows = [row.copy() for row in self.database.tables[self.table]
                if all(matches(row.get(key)) for key, matches in self.filters)]
        rows.sort(key=lambda row: row.get('id', 0), reverse=self.descending)
        return SimpleNamespace(data=rows[:self.page_limit])


class Database:
    def __init__(self):
        self.tables = {
            'alunos': [{'id': 17, 'professor_id': 5, 'nome': 'Aluno Teste',
                        'email': 'aluno@example.com', 'ativo': True, 'pin_acesso': 'secret-pin'}],
            'aluno_suporte_tea': [{'aluno_id': 17, 'nivel_suporte_tea': 2}],
            'historico_desempenho': [
                {'id': 1, 'aluno_id': 17, 'atividade_id': 3, 'quantidade_erros': 0},
                {'id': 2, 'aluno_id': 18, 'atividade_id': 4, 'segredo': 'other student'},
            ],
        }
        self.reads = []
        self.selections = []
        self.server_page_size = 137
        self.fail_table = None

    def table(self, name):
        return Query(self, name)


class PrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('tested_privacidade', ROOT/'src/privacidade.py')
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'src.bd_config': SimpleNamespace(supabase_admin=None)}):
            spec.loader.exec_module(cls.module)
        cls.app = Flask(__name__)
        cls.app.config.update(TESTING=True, SECRET_KEY='privacy-test-secret-at-least-32-characters')
        cls.app.register_blueprint(cls.module.privacidade_bp)

    def setUp(self):
        self.database = Database()
        self.module.supabase_admin = self.database
        self.client = self.app.test_client()
        self.body = {'solicitante': 'responsavel', 'verificacao_confirmada': True}
        self.url = '/professores/alunos/17/exportacao-dados'

    def headers(self, profile='professor', identifier=5):
        with self.app.app_context():
            token = gerar_token({'id': identifier, 'nome': 'Teste'}, perfil=profile)
        return {'Authorization': 'Bearer ' + token}

    def test_requires_authentication_and_teacher_role_before_database_access(self):
        for headers, expected in [({}, 401), (self.headers('aluno', 17), 403)]:
            response = self.client.post(self.url, json=self.body, headers=headers)
            self.assertEqual(response.status_code, expected)
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.database.reads, [])

    def test_browser_preflight_and_diagnostic_do_not_export_or_read_student_data(self):
        response = self.client.options(self.url, headers={
            'Origin': 'http://127.0.0.1:5501',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('POST', response.headers['Allow'])
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.database.reads, [])

    def test_other_teacher_cannot_read_student_or_history(self):
        response = self.client.post(self.url, json=self.body, headers=self.headers(identifier=6))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.database.reads, ['alunos'])

    def test_invalid_confirmation_or_extra_identity_is_rejected(self):
        for body in [None, [], {}, {'solicitante': 'responsavel', 'verificacao_confirmada': 'true'},
                     {**self.body, 'aluno_id': 18}, {**self.body, 'professor_id': 6},
                     {**self.body, 'solicitante': 'outro'}, {**self.body, 'verificacao_confirmada': False}]:
            response = self.client.post(self.url, json=body, headers=self.headers())
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database.reads, [])

    def test_export_has_only_owned_data_and_no_pin_or_credentials(self):
        response = self.client.post(self.url, json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['cadastro']['id'], 17)
        self.assertEqual(response.json['cadastro']['nivel_suporte_tea'], 2)
        self.assertEqual(len(response.json['historico_atividades']), 1)
        self.assertNotIn('pin_acesso', response.json['cadastro'])
        self.assertNotIn('secret-pin', response.text)
        self.assertNotIn('other student', response.text)
        self.assertEqual(response.json['exportacao']['professor_id'], 5)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')
        self.assertTrue(all('*' not in fields for _, fields in self.database.selections))

    def test_history_reads_all_pages_with_a_server_limit_lower_than_requested(self):
        self.database.tables['historico_desempenho'] = [
            {'id': index, 'aluno_id': 17, 'atividade_id': 3} for index in range(1, 1206)
        ]
        response = self.client.post(self.url, json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['historico_atividades']), 1205)
        self.assertEqual(response.json['historico_atividades'][-1]['id'], 1205)

    def test_empty_history_and_uninformed_support_are_explicit(self):
        self.database.tables['historico_desempenho'] = []
        self.database.tables['aluno_suporte_tea'] = []
        response = self.client.post(self.url, json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['historico_atividades'], [])
        self.assertIsNone(response.json['cadastro']['nivel_suporte_tea'])

    def test_failure_returns_no_partial_export_or_internal_details_and_can_retry(self):
        self.database.fail_table = 'historico_desempenho'
        response = self.client.post(self.url, json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('cadastro', response.json)
        self.assertNotIn('secret connection data', response.text)
        self.database.fail_table = None
        self.assertEqual(self.client.post(self.url, json=self.body, headers=self.headers()).status_code, 200)

    def test_missing_admin_client_and_large_history_fail_closed(self):
        self.module.supabase_admin = None
        self.assertEqual(self.client.post(self.url, json=self.body, headers=self.headers()).status_code, 503)
        self.module.supabase_admin = self.database
        with patch.object(self.module, 'MAX_HISTORY_ROWS', 0):
            response = self.client.post(self.url, json=self.body, headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('cadastro', response.json)


if __name__ == '__main__':
    unittest.main()
