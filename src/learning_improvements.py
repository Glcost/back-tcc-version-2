"""Authenticated learning preferences, word evidence and atomic database operations.

Only this server's administrative client may use the protected tables/RPCs.
Every route establishes the acting student or teacher before accessing them.
"""
from uuid import UUID, uuid4
from flask import Blueprint, current_app, jsonify, request
from auth import token_obrigatorio
from src.bd_config import supabase_admin

learning_bp = Blueprint("learning", __name__)
DEFAULT_GAME_PREFERENCES = {
    "pieceCount": None, "showHints": True,
    "memoryPreviewSeconds": 5, "advanceDelaySeconds": 1,
}


class LearningUnavailable(RuntimeError):
    pass


def private_database():
    if supabase_admin is None:
        raise LearningUnavailable("Configure o cliente administrativo do servidor e aplique a migração de melhorias dos jogos.")
    return supabase_admin


def atomic_operation(name, arguments):
    try:
        result = private_database().rpc(name, arguments).execute().data
        if not isinstance(result, dict):
            raise LearningUnavailable("O banco retornou uma resposta inválida.")
        return result
    except Exception as error:
        current_app.logger.error("Operação protegida indisponível: %s (%s)", name, type(error).__name__)
        raise LearningUnavailable("Não foi possível concluir a operação. Verifique a migração de melhorias dos jogos no servidor e tente novamente.") from None


def normalize_game_preferences(value, *, partial=False):
    if not isinstance(value, dict):
        raise ValueError("Envie um objeto com as preferências dos jogos.")
    if set(value) - set(DEFAULT_GAME_PREFERENCES):
        raise ValueError("Há preferências de jogos desconhecidas.")
    result = {} if partial else DEFAULT_GAME_PREFERENCES.copy()
    for field, item in value.items():
        if field == "pieceCount":
            valid = item is None or (type(item) is int and item in (2, 4, 6))
        elif field == "showHints":
            valid = type(item) is bool
        elif field == "memoryPreviewSeconds":
            valid = type(item) is int and item in (3, 5, 8, 10)
        else:
            valid = type(item) is int and item in (1, 2, 3, 5)
        if not valid:
            raise ValueError(f"Valor inválido para {field}.")
        result[field] = item
    return result


def normalize_word_evidence(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError("Envie até 128 palavras por atividade.")
    words = {}
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("palavra"), str):
            raise ValueError("Informe a palavra de cada resultado.")
        word = row["palavra"].strip().upper()
        if not word or len(word) > 100 or any(ord(char) < 32 for char in word):
            raise ValueError("Palavra inválida.")
        counts = {}
        for field in ("acertos", "erros", "ajudas"):
            count = row.get(field, 0)
            if type(count) is not int or not 0 <= count <= 10000:
                raise ValueError(f"Contagem inválida para {field}.")
            counts[field] = count
        if word in words:
            raise ValueError("Não repita a mesma palavra na atividade.")
        words[word] = {"palavra": word, **counts}
    return list(words.values())


def normalize_attempt_id(value):
    if value is None:
        # Compatibility for older clients. New clients persist one UUID until save succeeds.
        return str(uuid4())
    if not isinstance(value, str):
        raise ValueError("O identificador da tentativa deve ser um UUID.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("O identificador da tentativa deve ser um UUID.") from None


def unavailable_response():
    return jsonify({"erro": "O servidor precisa da migração de melhorias dos jogos e do cliente administrativo para esta operação.",
                    "code": "LEARNING_STORAGE_UNAVAILABLE"}), 503


@learning_bp.route("/health/learning", methods=["GET"])
def learning_readiness():
    """Read-only readiness check; a negative ID never reads a student's data."""
    try:
        result = atomic_operation("roar_student_word_report", {"p_aluno_id": -1})
        if not isinstance(result.get("palavras"), list):
            raise LearningUnavailable("Invalid readiness result")
        return jsonify({"status": "ready"}), 200
    except LearningUnavailable:
        return jsonify({"status": "unavailable"}), 503


def _authorized_student(student_id, *, teacher_only=False):
    professor_id = getattr(request, "professor_id", None)
    own_id = getattr(request, "aluno_id", None)
    if not professor_id and (teacher_only or own_id != student_id):
        return False
    query = private_database().table("alunos").select("id").eq("id", student_id).eq("ativo", True)
    if professor_id:
        query = query.eq("professor_id", professor_id)
    return bool(query.limit(1).execute().data)


def _read_preferences(student_id):
    rows = private_database().table("aluno_preferencias_jogos").select("preferencias").eq("aluno_id", student_id).limit(1).execute().data
    return normalize_game_preferences(rows[0]["preferencias"] if rows else {})


@learning_bp.route("/alunos/preferencias-jogos", methods=["GET"])
@token_obrigatorio
def student_game_preferences():
    student_id = getattr(request, "aluno_id", None)
    if not student_id:
        return jsonify({"erro": "Acesso permitido apenas para alunos.", "code": "FORBIDDEN"}), 403
    try:
        if not _authorized_student(student_id):
            return jsonify({"erro": "Aluno não encontrado.", "code": "STUDENT_NOT_FOUND"}), 404
        return jsonify(_read_preferences(student_id)), 200
    except Exception:
        return unavailable_response()


@learning_bp.route("/professores/alunos/<int:student_id>/preferencias-jogos", methods=["GET", "PATCH"])
@token_obrigatorio
def teacher_game_preferences(student_id):
    try:
        if not _authorized_student(student_id, teacher_only=True):
            return jsonify({"erro": "Acesso não autorizado a este aluno.", "code": "FORBIDDEN"}), 403
        if request.method == "GET":
            return jsonify(_read_preferences(student_id)), 200
        changes = normalize_game_preferences(request.get_json(silent=True), partial=True)
        if not changes:
            raise ValueError("Selecione uma preferência para salvar.")
        # Merging happens under the row lock in the RPC, avoiding lost partial edits.
        result = atomic_operation("roar_save_game_preferences", {
            "p_aluno_id": student_id, "p_professor_id": request.professor_id,
            "p_preferencias": changes,
        })
        status = result.pop("status", 200)
        return jsonify(result), status
    except ValueError as error:
        return jsonify({"erro": str(error), "code": "INVALID_GAME_PREFERENCES"}), 400
    except Exception:
        return unavailable_response()


@learning_bp.route("/relatorios/aluno/<int:student_id>/palavras", methods=["GET"])
@token_obrigatorio
def student_word_report(student_id):
    try:
        if not _authorized_student(student_id):
            return jsonify({"erro": "Acesso não autorizado a este aluno.", "code": "FORBIDDEN"}), 403
        result = atomic_operation("roar_student_word_report", {"p_aluno_id": student_id})
        return jsonify({"aluno_id": student_id, "palavras": result.get("palavras", [])}), 200
    except Exception:
        return unavailable_response()
