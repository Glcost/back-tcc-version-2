"""Private TEA support data. Callers must authorize the student before access.

The protected table is separate from the legacy student table and is accessed
exclusively with the server's service role. There is no public-client fallback.
"""

import logging

from src.bd_config import supabase_admin


logger = logging.getLogger(__name__)


class SuporteTeaIndisponivel(RuntimeError):
    pass


def validar_nivel_suporte_tea(valor):
    if valor is None:
        return None
    if type(valor) is not int or valor not in (1, 2, 3):
        raise ValueError(
            "O nível de suporte TEA deve ser 1, 2, 3 ou não informado."
        )
    return valor


def exigir_configuracao_suporte_tea():
    if supabase_admin is None:
        raise SuporteTeaIndisponivel(
            "O servidor não está configurado para salvar o nível de suporte TEA."
        )


def buscar_niveis_suporte_tea(aluno_ids):
    ids = list(dict.fromkeys(aluno_ids))
    if not ids or supabase_admin is None:
        return {}

    try:
        resultado = (
            supabase_admin
            .table("aluno_suporte_tea")
            .select("aluno_id, nivel_suporte_tea")
            .in_("aluno_id", ids)
            .execute()
        )
        return {
            row["aluno_id"]: row.get("nivel_suporte_tea")
            for row in resultado.data or []
        }
    except Exception:
        logger.error("Falha ao consultar a configuração privada de suporte TEA.")
        raise SuporteTeaIndisponivel(
            "Não foi possível consultar o nível de suporte TEA."
        ) from None


def buscar_nivel_suporte_tea(aluno_id):
    return buscar_niveis_suporte_tea([aluno_id]).get(aluno_id)


def salvar_nivel_suporte_tea(aluno_id, nivel):
    nivel = validar_nivel_suporte_tea(nivel)
    exigir_configuracao_suporte_tea()
    try:
        (
            supabase_admin
            .table("aluno_suporte_tea")
            .upsert({
                "aluno_id": aluno_id,
                "nivel_suporte_tea": nivel,
            }, on_conflict="aluno_id")
            .execute()
        )
    except Exception:
        logger.error("Falha ao salvar a configuração privada de suporte TEA.")
        raise SuporteTeaIndisponivel(
            "Não foi possível salvar o nível de suporte TEA."
        ) from None
