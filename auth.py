import jwt

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, jsonify, request


ALLOWED_PROFILES = {"professor", "aluno"}
TOKEN_DURATION_HOURS = 8
JWT_ALGORITHM = "HS256"


def _get_secret_key():
    secret_key = current_app.config.get("SECRET_KEY")

    if not secret_key:
        raise RuntimeError(
            "A variável SECRET_KEY não foi configurada."
        )

    return secret_key


def _normalize_user_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def gerar_token(usuario, perfil="professor"):
    """
    Gera um JWT para professor ou aluno.

    O claim `sub` segue o padrão JWT e deve ser uma string.
    """

    if perfil not in ALLOWED_PROFILES:
        raise ValueError(
            f"Perfil de autenticação inválido: {perfil}"
        )

    usuario_id = _normalize_user_id(
        usuario.get("id")
    )

    if not usuario_id:
        raise ValueError(
            "O usuário não possui um ID válido."
        )

    agora = datetime.now(timezone.utc)

    payload = {
        "sub": str(usuario_id),
        "nome": str(usuario.get("nome", "")),
        "perfil": perfil,
        "iat": agora,
        "exp": agora + timedelta(
            hours=TOKEN_DURATION_HOURS
        ),
    }

    if perfil == "professor":
        payload["professor_id"] = usuario_id

    if perfil == "aluno":
        payload["aluno_id"] = usuario_id

    return jwt.encode(
        payload,
        _get_secret_key(),
        algorithm=JWT_ALGORITHM,
    )


def token_obrigatorio(func):
    """
    Protege uma rota e disponibiliza os dados do usuário
    autenticado no objeto request.
    """

    @wraps(func)
    def verificar_token(*args, **kwargs):
        authorization = request.headers.get(
            "Authorization",
            "",
        ).strip()

        parts = authorization.split()

        has_valid_format = (
            len(parts) == 2
            and parts[0].lower() == "bearer"
            and parts[1]
        )

        if not has_valid_format:
            return jsonify({
                "erro": (
                    "Token ausente ou cabeçalho Authorization inválido."
                    "inválido."
                ),
                "code": "INVALID_AUTHORIZATION_HEADER",
            }), 401

        token = parts[1]

        try:
            token_data = jwt.decode(
                token,
                _get_secret_key(),
                algorithms=[JWT_ALGORITHM],
            )

            user_id = _normalize_user_id(
                token_data.get("sub")
            )

            profile = token_data.get("perfil")

            if not user_id:
                return jsonify({
                    "erro": "O token não possui um usuário válido.",
                    "code": "INVALID_TOKEN_SUBJECT",
                }), 401

            if profile not in ALLOWED_PROFILES:
                return jsonify({
                    "erro": "O token não possui um perfil válido.",
                    "code": "INVALID_TOKEN_PROFILE",
                }), 401

            request.usuario_logado = token_data
            request.usuario_id = user_id
            request.perfil = profile

            request.professor_id = (
                user_id
                if profile == "professor"
                else None
            )

            request.aluno_id = (
                user_id
                if profile == "aluno"
                else None
            )

        except jwt.ExpiredSignatureError:
            return jsonify({
                "erro": (
                    "Sessão expirada. Faça login novamente."
                ),
                "code": "TOKEN_EXPIRED",
            }), 401

        except jwt.InvalidTokenError as error:
            current_app.logger.warning(
                "JWT inválido: %s",
                str(error),
            )

            return jsonify({
                "erro": "Token de acesso inválido.",
                "code": "INVALID_TOKEN",
            }), 401

        except RuntimeError as error:
            current_app.logger.error(str(error))

            return jsonify({
                "erro": (
                    "O servidor não está configurado "
                    "corretamente para autenticação."
                ),
                "code": "AUTH_CONFIGURATION_ERROR",
            }), 500

        return func(*args, **kwargs)

    return verificar_token