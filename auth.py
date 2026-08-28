import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify, current_app

# ==========================
# FUNÇÃO PARA GERAR TOKEN JWT
# ==========================
def gerar_token(usuario):
    """
    Gera um token JWT com tempo de expiração.

    Parâmetro:
    - usuario: dicionário com 'id' e 'nome' do professor

    Retorno:
    - token JWT assinado com a SECRET_KEY da aplicação
    """
    payload = {
        "professor_id": usuario["id"],   # ID do professor
        "nome": usuario["nome"],
        "perfil": "professor",           # perfil fixo
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }

    token = jwt.encode(
        payload,
        current_app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    return token


# ==========================
# DECORATOR PARA PROTEGER ROTAS
# ==========================
def token_obrigatorio(func):
    """
    Decorator que exige um token JWT válido para acessar a rota.
    Após validação, armazena o professor_id em request.professor_id.
    """
    @wraps(func)
    def verificar_token(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"erro": "Token ausente. Faça login."}), 401

        partes = auth_header.split()
        if len(partes) != 2 or partes[0] != "Bearer":
            return jsonify({"erro": "Cabeçalho Authorization inválido."}), 401

        token = partes[1]

        try:
            dados_token = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )
            # Extrai o professor_id do token e guarda na requisição
            professor_id = dados_token.get("professor_id")
            if not professor_id:
                return jsonify({"erro": "Token não contém identificador do professor."}), 401

            request.professor_id = professor_id
            request.usuario_logado = dados_token  # opcional, para outros dados

        except jwt.ExpiredSignatureError:
            return jsonify({"erro": "Token expirado. Faça login novamente."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"erro": "Token inválido."}), 401

        return func(*args, **kwargs)

    return verificar_token