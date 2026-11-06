"""Teacher-assisted export of one student's registration and activity history."""

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from auth import token_obrigatorio
from src.bd_config import supabase_admin


privacidade_bp = Blueprint("privacidade", __name__)
CADASTRO_FIELDS = (
    "id", "nome", "email", "ano_escolar", "modo_aprendizagem",
    "criado_em", "ativo", "xp_total",
)
HISTORICO_FIELDS = (
    "id", "atividade_id", "modo_utilizado", "quantidade_erros",
    "tempo_segundos", "concluido", "data_hora",
)
PAGE_SIZE = 500
MAX_HISTORY_ROWS = 50000


class HistoricoMuitoGrande(RuntimeError):
    pass


def buscar_historico_exportacao(database, aluno_id):
    # Freeze the upper ID so new attempts cannot extend pagination indefinitely.
    ultima = (
        database.table("historico_desempenho").select("id")
        .eq("aluno_id", aluno_id).order("id", desc=True).limit(1).execute()
    ).data or []
    if not ultima:
        return []
    limite_id = ultima[0]["id"]
    historico = []
    cursor = 0
    while True:
        pagina = (
            database.table("historico_desempenho").select(", ".join(HISTORICO_FIELDS))
            .eq("aluno_id", aluno_id).gt("id", cursor).lte("id", limite_id)
            .order("id").limit(PAGE_SIZE).execute()
        ).data or []
        if not pagina:
            break
        if len(historico) + len(pagina) > MAX_HISTORY_ROWS:
            raise HistoricoMuitoGrande()
        proximo_cursor = pagina[-1]["id"]
        if proximo_cursor <= cursor:
            raise RuntimeError("Invalid history cursor")
        historico.extend({field: row.get(field) for field in HISTORICO_FIELDS} for row in pagina)
        cursor = proximo_cursor
        if cursor >= limite_id:
            break
    return historico


@privacidade_bp.after_request
def proteger_resposta(response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@privacidade_bp.route("/professores/alunos/<int:aluno_id>/exportacao-dados", methods=["POST"])
@token_obrigatorio
def exportar_dados_aluno(aluno_id):
    professor_id = getattr(request, "professor_id", None)
    if not professor_id:
        return jsonify(erro="A exportação deve ser realizada pelo professor da turma.",
                       code="TEACHER_ACCESS_REQUIRED"), 403

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or set(dados) != {"solicitante", "verificacao_confirmada"}:
        return jsonify(erro="Informe o tipo de solicitante e a confirmação da verificação.",
                       code="INVALID_EXPORT_REQUEST"), 400
    if dados["solicitante"] not in ("titular", "responsavel") or dados["verificacao_confirmada"] is not True:
        return jsonify(erro="Confirme a identidade e a autorização do solicitante antes de exportar.",
                       code="VERIFICATION_REQUIRED"), 400
    if supabase_admin is None:
        return jsonify(erro="A exportação está temporariamente indisponível.",
                       code="EXPORT_UNAVAILABLE"), 503

    try:
        alunos = (
            supabase_admin.table("alunos").select(", ".join(CADASTRO_FIELDS))
            .eq("id", aluno_id).eq("professor_id", professor_id).limit(1).execute()
        ).data or []
        if not alunos:
            return jsonify(erro="Aluno indisponível para este professor.",
                           code="STUDENT_ACCESS_DENIED"), 403

        cadastro = {field: alunos[0].get(field) for field in CADASTRO_FIELDS}
        suporte = (
            supabase_admin.table("aluno_suporte_tea").select("nivel_suporte_tea")
            .eq("aluno_id", aluno_id).limit(1).execute()
        ).data or []
        cadastro["nivel_suporte_tea"] = suporte[0].get("nivel_suporte_tea") if suporte else None
        historico = buscar_historico_exportacao(supabase_admin, aluno_id)
        identificador = str(uuid4())
        response = jsonify({
            "versao": 1,
            "exportacao": {
                "id": identificador,
                "gerada_em": datetime.now(timezone.utc).isoformat(),
                "professor_id": professor_id,
                "solicitante": dados["solicitante"],
                "verificacao": "Identidade e autorização confirmadas manualmente pelo professor.",
                "escopo": "Cadastro atual e histórico das atividades deste aluno.",
                "total_registros_historico": len(historico),
            },
            "cadastro": cadastro,
            "historico_atividades": historico,
        })
        response.headers["Content-Disposition"] = f'attachment; filename="roar-aluno-{aluno_id}.json"'
        current_app.logger.info("Exportacao de dados gerada id=%s professor_id=%s aluno_id=%s",
                                identificador, professor_id, aluno_id)
        return response, 200
    except HistoricoMuitoGrande:
        return jsonify(erro="O histórico excede o tamanho atendido por esta exportação.",
                       code="EXPORT_HISTORY_TOO_LARGE"), 422
    except Exception:
        current_app.logger.error("Falha na exportacao de dados do aluno.")
        return jsonify(erro="Não foi possível exportar os dados. Tente novamente.",
                       code="EXPORT_FAILED"), 503
