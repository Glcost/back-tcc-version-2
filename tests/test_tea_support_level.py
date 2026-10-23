"""API contracts without a Flask app, credentials, or a database connection.

Only the tested functions are compiled from the production AST. Route decorators
are omitted so importing this suite never initializes the remote Supabase client.
Run: python -m unittest discover -s tests -v
"""

import ast
import collections
import logging
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_functions(filename, names, namespace):
    tree = ast.parse((ROOT / "src" / filename).read_text(encoding="utf-8"))
    functions = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name in names:
            item.decorator_list = []
            functions.append(item)
    if {item.name for item in functions} != set(names):
        raise AssertionError("A production function required by the test is missing")
    exec(compile(ast.Module(body=functions, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class MemoryDatabase:
    def __init__(self, student=None):
        self.student = student
        self.writes = []
        self.queries = []
        self.private_levels = {}
        self.executions = []
        self.fail = False

    def table(self, table):
        return MemoryQuery(self, table)


class MemoryQuery:
    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.operation = "select"
        self.payload = None
        self.filters = []
        self.single_row = False
        self.columns = "*"

    def select(self, columns="*"):
        self.database.queries.append((self.table, columns))
        self.columns = columns
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def in_(self, key, values):
        self.filters.append((key, list(values)))
        return self

    def limit(self, *_args):
        return self

    def maybe_single(self):
        self.single_row = True
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload.copy()
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload.copy()
        return self

    def upsert(self, payload, **_kwargs):
        self.operation, self.payload = "upsert", payload.copy()
        return self

    def execute(self):
        self.database.executions.append((self.table, self.operation, self.filters))
        if self.database.fail:
            raise RuntimeError("Database detail that must not reach users")
        if self.operation != "select":
            self.database.writes.append((
                self.table, self.operation, self.payload, self.filters,
            ))
            if self.table == "alunos":
                if "nivel_suporte_tea" in self.payload:
                    raise AssertionError("Private TEA data written to legacy table")
                if self.operation == "insert":
                    self.database.student = {"id": 17, "ativo": True, **self.payload}
                else:
                    self.database.student.update(self.payload)
            elif self.table == "aluno_suporte_tea":
                self.database.private_levels[self.payload["aluno_id"]] = (
                    self.payload["nivel_suporte_tea"]
                )
                return SimpleNamespace(data=[self.payload])
            else:
                return SimpleNamespace(data=[{"id": 29, **self.payload}])
        if self.table == "aluno_suporte_tea":
            requested = dict(self.filters)["aluno_id"]
            return SimpleNamespace(data=[
                {"aluno_id": aluno_id, "nivel_suporte_tea": level}
                for aluno_id, level in self.database.private_levels.items()
                if aluno_id in requested
            ])
        if "nivel_suporte_tea" in self.columns:
            raise AssertionError("Private TEA data selected from legacy table")
        student = self.database.student
        if student and any(student.get(key) != value for key, value in self.filters):
            student = None
        return SimpleNamespace(data=(
            student if self.single_row else [student] if student else []
        ))


class TeaSupportLevelTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryDatabase()
        self.private_db = MemoryDatabase()
        self.helper = load_functions("suporte_tea.py", [
            "SuporteTeaIndisponivel", "validar_nivel_suporte_tea",
            "exigir_configuracao_suporte_tea", "buscar_niveis_suporte_tea",
            "buscar_nivel_suporte_tea", "salvar_nivel_suporte_tea",
        ], {
            "supabase_admin": self.private_db,
            "logger": logging.getLogger(__name__),
        })
        self.request = SimpleNamespace(
            professor_id=5,
            aluno_id=17,
            get_json=lambda **_kwargs: self.body,
        )
        self.body = {
            "nome": "Aluno de teste",
            "email": "aluno@example.com",
            "ano_escolar": "3º ano",
            "pergunta_a": "A1",
            "pergunta_b": "B1",
        }
        self.namespace = load_functions("professora.py", [
            "normalizar_email", "email_tem_formato_valido",
            "cadastrar_e_avaliar_aluno", "editar_aluno", "lista_alunos",
        ], {
            **self.helper,
            "request": self.request,
            "supabase": self.db,
            "jsonify": lambda payload: payload,
            "PADRAO_EMAIL": re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$"),
            "email_ja_cadastrado": lambda *_args, **_kwargs: False,
            "gerar_pin_aluno": lambda: "1234",
            "verificar_professor_aluno": lambda aluno, professor: professor == 5,
            "verificar_professor": lambda route_id, token_id: route_id == token_id,
        })

    def create(self):
        return self.namespace["cadastrar_e_avaliar_aluno"]()

    def test_accepts_only_null_or_integers_one_to_three(self):
        validate = self.namespace["validar_nivel_suporte_tea"]
        for value in (None, 1, 2, 3):
            with self.subTest(value=value):
                self.assertEqual(validate(value), value)
        for value in (True, False, 1.0, 2.5, "1", "", 0, 4, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate(value)

    def test_create_does_not_infer_tea_level_from_triage(self):
        response, status = self.create()
        self.assertEqual(status, 201)
        self.assertEqual(response["nivel_identificado"], 1)
        self.assertIsNone(response["nivel_suporte_tea"])
        self.assertNotIn("nivel_suporte_tea", self.db.student)
        self.assertEqual(self.private_db.writes, [])

    def test_create_preserves_separate_tea_level_and_learning_mode(self):
        self.body.update(pergunta_a="A3", pergunta_b="B3", nivel_suporte_tea=3)
        response, status = self.create()
        self.assertEqual(status, 201)
        self.assertEqual(response["nivel_identificado"], 3)
        self.assertEqual(self.private_db.private_levels[17], 3)
        self.assertNotIn("nivel_suporte_tea", self.db.student)
        self.assertEqual(self.db.student["modo_aprendizagem"], "Nível 3 - Autonomia Contextual")

    def test_create_invalid_tea_level_never_writes(self):
        self.body["nivel_suporte_tea"] = True
        response, status = self.create()
        self.assertEqual(status, 400)
        self.assertEqual(response["code"], "INVALID_TEA_SUPPORT_LEVEL")
        self.assertEqual(self.db.writes, [])
        self.assertEqual(self.private_db.writes, [])

    def test_update_changes_tea_only_and_can_clear_it(self):
        self.body["nivel_suporte_tea"] = 1
        self.create()
        original_mode = self.db.student["modo_aprendizagem"]
        self.body = {"nivel_suporte_tea": 2}
        response, status = self.namespace["editar_aluno"](17)
        self.assertEqual(status, 200)
        self.assertEqual(response["aluno"]["nivel_suporte_tea"], 2)
        self.assertEqual(self.db.student["modo_aprendizagem"], original_mode)
        self.assertIn(("professor_id", 5), self.db.executions[-1][2])
        self.assertEqual(self.private_db.private_levels[17], 2)
        self.body = {"nivel_suporte_tea": None}
        response, status = self.namespace["editar_aluno"](17)
        self.assertEqual(status, 200)
        self.assertIsNone(response["aluno"]["nivel_suporte_tea"])
        self.assertIsNone(self.private_db.private_levels[17])

    def test_update_omitted_tea_level_preserves_existing_value(self):
        self.body["nivel_suporte_tea"] = 3
        self.create()
        self.body = {"nome": "Novo nome"}
        _response, status = self.namespace["editar_aluno"](17)
        self.assertEqual(status, 200)
        self.assertEqual(self.private_db.private_levels[17], 3)

    def test_update_rejects_invalid_values_before_writing(self):
        self.create()
        previous_writes = len(self.db.writes)
        previous_private_writes = len(self.private_db.writes)
        for value in (False, "2", 1.0, 0, 4):
            with self.subTest(value=value):
                self.body = {"nivel_suporte_tea": value}
                response, status = self.namespace["editar_aluno"](17)
                self.assertEqual(status, 400)
                self.assertEqual(response["code"], "INVALID_TEA_SUPPORT_LEVEL")
                self.assertEqual(len(self.db.writes), previous_writes)
                self.assertEqual(len(self.private_db.writes), previous_private_writes)

    def test_other_professor_cannot_update_tea_level(self):
        self.request.professor_id = 9
        self.body = {"nivel_suporte_tea": 2}
        _response, status = self.namespace["editar_aluno"](17)
        self.assertEqual(status, 403)
        self.assertEqual(self.db.writes, [])
        self.assertEqual(self.private_db.executions, [])

    def test_login_and_me_return_saved_level_without_changing_learning_mode(self):
        self.body["nivel_suporte_tea"] = 3
        self.create()
        functions = load_functions("aluno.py", ["login_aluno", "obter_aluno_atual"], {
            **self.helper,
            "request": self.request,
            "supabase": self.db,
            "jsonify": lambda payload: payload,
            "gerar_token": lambda *_args, **_kwargs: "test-token",
            "calcular_ofensiva": lambda _id: 0,
        })
        self.body = {"pin": "1234", "email": "aluno@example.com"}
        login, status = functions["login_aluno"]()
        self.assertEqual(status, 200)
        self.assertEqual(login["user"]["teaSupportLevel"], 3)
        profile, status = functions["obter_aluno_atual"]()
        self.assertEqual(status, 200)
        self.assertEqual(profile["teaSupportLevel"], 3)
        self.assertEqual(profile["supportLevel"], "Nível 1 - Suporte Visual Puro")
        self.private_db.private_levels.pop(17)
        # Even if a legacy value exists, it must never be used as fallback.
        self.db.student["nivel_suporte_tea"] = 1
        profile, status = functions["obter_aluno_atual"]()
        self.assertEqual(status, 200)
        self.assertIsNone(profile["teaSupportLevel"])

    def test_teacher_report_carries_saved_tea_level_to_editing_screen(self):
        self.body["nivel_suporte_tea"] = 2
        self.create()
        summary = {
            "tentativas_totais": 0, "atividades_concluidas": 0,
            "media_erros": 0, "media_tempo_segundos": 0,
            "taxa_conclusao_pct": 0,
        }
        functions = load_functions("relatorios.py", [
            "_buscar_alunos_professor", "relatorio_professor",
        ], {
            **self.helper,
            "_db": self.db,
            "jsonify": lambda payload: payload,
            "_validar_professor": lambda _id: None,
            "_buscar_atividades_disponiveis_por_modo": lambda _modes: {},
            "_buscar_historico_alunos": lambda _ids: [],
            "_calcular_resumo": lambda *_args: summary,
            "_inteiro": lambda value: int(value or 0),
            "_ultimo_acesso": lambda _records: None,
            "_media": lambda _values: 0,
            "Counter": collections.Counter,
            "defaultdict": collections.defaultdict,
        })
        response, status = functions["relatorio_professor"](5)
        self.assertEqual(status, 200)
        self.assertEqual(response["alunos"][0]["nivel_suporte_tea"], 2)
        self.assertNotIn("nivel_suporte_tea", self.db.queries[-1][1])
        self.assertEqual(self.private_db.executions[-1][2], [("aluno_id", [17])])

    def test_missing_admin_configuration_blocks_create_before_any_write(self):
        self.helper["supabase_admin"] = None
        for level in (1, None):
            with self.subTest(level=level):
                self.body["nivel_suporte_tea"] = level
                response, status = self.create()
                self.assertEqual(status, 503)
                self.assertEqual(response["code"], "TEA_SUPPORT_UNAVAILABLE")
                self.assertEqual(self.db.writes, [])
                self.assertEqual(self.private_db.writes, [])

    def test_private_write_failure_keeps_assessment_and_reports_created_student(self):
        self.private_db.fail = True
        self.body["nivel_suporte_tea"] = 2
        response, status = self.create()
        self.assertEqual(status, 503)
        self.assertEqual(response["code"], "STUDENT_CREATED_TEA_SUPPORT_FAILED")
        self.assertEqual(response["aluno_id"], 17)
        self.assertIn("Aluno cadastrado", response["erro"])
        self.assertIn("página Alunos", response["erro"])
        self.assertEqual([write[0] for write in self.db.writes], [
            "alunos", "avaliacao_inicial",
        ])

    def test_missing_admin_blocks_mixed_update_before_any_write(self):
        self.create()
        original_name = self.db.student["nome"]
        before = len(self.db.writes)
        self.helper["supabase_admin"] = None
        self.body = {"nome": "Nome novo", "nivel_suporte_tea": 1}
        response, status = self.namespace["editar_aluno"](17)
        self.assertEqual(status, 503)
        self.assertEqual(response["code"], "TEA_SUPPORT_UNAVAILABLE")
        self.assertEqual(len(self.db.writes), before)
        self.assertEqual(self.db.student["nome"], original_name)

    def test_teacher_list_reads_private_level_only_for_owned_students(self):
        self.body["nivel_suporte_tea"] = 2
        self.create()
        self.private_db.private_levels[99] = 3
        response, status = self.namespace["lista_alunos"](5)
        self.assertEqual(status, 200)
        self.assertEqual(response[0]["nivel_suporte_tea"], 2)
        self.assertEqual(self.private_db.executions[-1][2], [("aluno_id", [17])])
        before = len(self.private_db.executions)
        response, status = self.namespace["lista_alunos"](9)
        self.assertEqual(status, 403)
        self.assertEqual(len(self.private_db.executions), before)

    def test_invalid_login_and_non_student_profile_never_read_private_data(self):
        self.create()
        functions = load_functions("aluno.py", ["login_aluno", "obter_aluno_atual"], {
            **self.helper, "request": self.request, "supabase": self.db,
            "jsonify": lambda payload: payload,
        })
        self.body = {"pin": "0000", "email": "aluno@example.com"}
        _, status = functions["login_aluno"]()
        self.assertEqual(status, 401)
        self.request.aluno_id = None
        _, status = functions["obter_aluno_atual"]()
        self.assertEqual(status, 403)
        self.assertEqual(self.private_db.executions, [])

    def test_denied_activity_and_report_access_never_reads_private_data(self):
        denied = ({"code": "FORBIDDEN"}, 403)
        activity = load_functions("atividades.py", ["carregar_atividades_modulo"], {
            **self.helper,
            "validar_acesso_do_aluno": lambda _id: (None, denied),
        })
        self.assertEqual(activity["carregar_atividades_modulo"](1, 99), denied)
        reports = load_functions("relatorios.py", [
            "relatorio_professor", "relatorio_aluno",
        ], {
            **self.helper,
            "_validar_professor": lambda _id: denied,
            "_validar_acesso_ao_aluno": lambda _id: denied,
        })
        self.assertEqual(reports["relatorio_professor"](9), denied)
        self.assertEqual(reports["relatorio_aluno"](99), denied)
        self.assertEqual(self.private_db.executions, [])

    def test_helper_uses_only_admin_and_limits_reads_to_requested_students(self):
        self.private_db.private_levels = {17: 2, 99: 3}
        levels = self.helper["buscar_niveis_suporte_tea"]([17, 17])
        self.assertEqual(levels, {17: 2})
        self.assertEqual(self.private_db.executions[-1][2], [("aluno_id", [17])])
        self.assertEqual(self.db.executions, [])
        self.helper["salvar_nivel_suporte_tea"](17, None)
        self.assertIsNone(self.private_db.private_levels[17])
        self.assertEqual(self.private_db.private_levels[99], 3)
        self.assertEqual(self.db.writes, [])

    def test_helper_without_admin_does_not_fall_back_to_public_client(self):
        self.helper["supabase_admin"] = None
        self.db.student = {"id": 17, "nivel_suporte_tea": 3}
        self.assertIsNone(self.helper["buscar_nivel_suporte_tea"](17))
        with self.assertRaises(self.helper["SuporteTeaIndisponivel"]):
            self.helper["salvar_nivel_suporte_tea"](17, 2)
        self.assertEqual(self.db.executions, [])
        self.assertEqual(self.private_db.executions, [])

    def test_helper_database_failures_do_not_expose_internal_errors(self):
        self.private_db.fail = True
        with self.assertRaises(self.helper["SuporteTeaIndisponivel"]) as error:
            self.helper["buscar_nivel_suporte_tea"](17)
        self.assertNotIn("Database detail", str(error.exception))
        with self.assertRaises(self.helper["SuporteTeaIndisponivel"]) as error:
            self.helper["salvar_nivel_suporte_tea"](17, 1)
        self.assertNotIn("Database detail", str(error.exception))


if __name__ == "__main__":
    unittest.main()
