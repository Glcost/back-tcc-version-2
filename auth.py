# auth.py
import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify, current_app

def gerar_token(usuario, perfil="professor"):
    """
    Gera um token JWT com claim dinamica de perfil ('professor' ou 'aluno').
    """
    payload = {
        "sub": usuario["id"],
        "nome": usuario.get("nome", ""),
        "perfil": perfil,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8)
    }
    
    if perfil == "professor":
        payload["professor_id"] = usuario["id"]
    elif perfil == "aluno":
        payload["aluno_id"] = usuario["id"]

    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")

def token_obrigatorio(func):
    """
    Decorator para proteção de rotas privadas. Extrai o ID e o perfil do usuário do token.
    """
    @wraps(func)
    def verificar_token(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"erro": "Token ausente. Faça login para continuar.", "code": "UNAUTHORIZED"}), 401

        partes = auth_header.split()
        if len(partes) != 2 or partes[0] != "Bearer":
            return jsonify({"erro": "Formato de cabeçalho Authorization inválido.", "code": "INVALID_HEADER"}), 401

        token = partes[1]

        try:
            dados_token = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )
            request.usuario_logado = dados_token
            request.professor_id = dados_token.get("professor_id")
            request.aluno_id = dados_token.get("aluno_id")

        except jwt.ExpiredSignatureError:
            return jsonify({"erro": "Sessão expirada. Faça login novamente.", "code": "TOKEN_EXPIRED"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"erro": "Token de acesso inválido.", "code": "INVALID_TOKEN"}), 401

        return func(*args, **kwargs)

    return verificar_token