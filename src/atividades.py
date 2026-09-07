from flask import Blueprint, jsonify, request

from auth import token_obrigatorio
from src.bd_config import supabase


atividades_bp = Blueprint("atividades", __name__)


MODOS_APRENDIZAGEM = {
    "Nível 1 - Suporte Visual Puro",
    "Nível 2 - Aprendiz Guiado",
    "Nível 3 - Autonomia Contextual",
}

TIPOS_INTERACAO = {
    "Tap",
    "DragAndDrop",
    "MultiplaEscolha",
    "Associacao",
}

XP_BASE_POR_ATIVIDADE = 50
XP_MINIMO_POR_CONCLUSAO = 10
MAXIMO_ERROS = 1000
MAXIMO_TEMPO_SEGUNDOS = 86400


def resposta_erro(mensagem, codigo, status):
    return jsonify({
        "erro": mensagem,
        "code": codigo,
    }), status


def converter_inteiro(
    valor,
    nome_campo,
    *,
    minimo=0,
    maximo=None,
):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValueError(
            f"O campo '{nome_campo}' deve ser um número inteiro."
        )

    if numero < minimo:
        raise ValueError(
            f"O campo '{nome_campo}' deve ser maior ou igual a {minimo}."
        )

    if maximo is not None and numero > maximo:
        raise ValueError(
            f"O campo '{nome_campo}' deve ser menor ou igual a {maximo}."
        )

    return numero


def converter_booleano(valor, nome_campo):
    if isinstance(valor, bool):
        return valor

    if valor in (1, "1", "true", "True"):
        return True

    if valor in (0, "0", "false", "False"):
        return False

    raise ValueError(
        f"O campo '{nome_campo}' deve ser verdadeiro ou falso."
    )


def obter_aluno_autenticado():
    aluno_id = getattr(request, "aluno_id", None)

    if not aluno_id:
        return None

    try:
        return int(aluno_id)
    except (TypeError, ValueError):
        return None


def validar_acesso_do_aluno(aluno_id_url):
    aluno_id_token = obter_aluno_autenticado()

    if not aluno_id_token:
        return None, resposta_erro(
            "Acesso permitido apenas para alunos.",
            "STUDENT_ACCESS_REQUIRED",
            403,
        )

    if aluno_id_token != aluno_id_url:
        return None, resposta_erro(
            "Você não pode acessar atividades de outro aluno.",
            "STUDENT_ACCESS_DENIED",
            403,
        )

    return aluno_id_token, None


def buscar_aluno(aluno_id):
    resultado = (
        supabase
        .table("alunos")
        .select(
            "id, nome, modo_aprendizagem, xp_total"
        )
        .eq("id", aluno_id)
        .single()
        .execute()
    )

    return resultado.data


def buscar_modulo(modulo_id):
    resultado = (
        supabase
        .table("modulos")
        .select("id, nome, ativo")
        .eq("id", modulo_id)
        .single()
        .execute()
    )

    return resultado.data


def buscar_itens_modulo(modulo_id):
    resultado = (
        supabase
        .table("itens_modulo")
        .select(
            (
                "id, modulo_id, palavra_pt, palavra_en, "
                "url_imagem_real, url_imagem_vetor, "
                "ordem, ativo"
            )
        )
        .eq("modulo_id", modulo_id)
        .eq("ativo", True)
        .order("ordem")
        .execute()
    )

    return resultado.data or []


def normalizar_itens_modulo(itens):
    itens_normalizados = []
    itens_invalidos = []

    for item in itens:
        item_id = item.get("id")
        palavra_pt = str(
            item.get("palavra_pt") or ""
        ).strip()
        palavra_en = str(
            item.get("palavra_en") or ""
        ).strip().upper()
        url_imagem_real = str(
            item.get("url_imagem_real") or ""
        ).strip()
        url_imagem_vetor = str(
            item.get("url_imagem_vetor") or ""
        ).strip()

        try:
            ordem = converter_inteiro(
                item.get("ordem"),
                "ordem",
                minimo=1,
            )
        except ValueError:
            ordem = None

        if (
            not item_id
            or not palavra_pt
            or not palavra_en
            or not url_imagem_real
            or not url_imagem_vetor
            or ordem is None
        ):
            itens_invalidos.append(item_id)
            continue

        itens_normalizados.append({
            "item_id": int(item_id),
            "palavra_pt": palavra_pt,
            "palavra_en": palavra_en,
            "url_imagem_real": url_imagem_real,
            "url_imagem_vetor": url_imagem_vetor,
            "ordem": ordem,
        })

    return itens_normalizados, itens_invalidos


def calcular_xp(quantidade_erros):
    penalidade = quantidade_erros * 5

    return max(
        XP_MINIMO_POR_CONCLUSAO,
        XP_BASE_POR_ATIVIDADE - penalidade,
    )


@atividades_bp.route("/modulos", methods=["GET"])
@token_obrigatorio
def listar_modulos():
    try:
        modulos_resultado = (
            supabase
            .table("modulos")
            .select("id, nome, ativo")
            .eq("ativo", True)
            .order("id")
            .execute()
        )
        modulos = modulos_resultado.data or []
        aluno_id = getattr(request, "aluno_id", None)

        if not aluno_id:
            return jsonify(modulos), 200

        atividades_resultado = (
            supabase
            .table("atividades")
            .select("id, modulo_id, ordem_sequencia")
            .order("ordem_sequencia")
            .execute()
        )
        atividades = atividades_resultado.data or []
        ids_atividades = [atividade["id"] for atividade in atividades]
        concluidas = set()

        if ids_atividades:
            historico_resultado = (
                supabase
                .table("historico_desempenho")
                .select("atividade_id")
                .eq("aluno_id", int(aluno_id))
                .eq("concluido", True)
                .in_("atividade_id", ids_atividades)
                .execute()
            )
            concluidas = {
                registro["atividade_id"]
                for registro in (historico_resultado.data or [])
            }

        resposta = []
        for modulo in modulos:
            atividades_modulo = [
                atividade for atividade in atividades
                if atividade.get("modulo_id") == modulo["id"]
            ]
            total = len(atividades_modulo)
            total_concluidas = sum(
                1 for atividade in atividades_modulo
                if atividade["id"] in concluidas
            )
            pendentes = [
                atividade for atividade in atividades_modulo
                if atividade["id"] not in concluidas
            ]

            if total == 0:
                status = "preparation"
                proxima_etapa = None
            elif total_concluidas == total:
                status = "completed"
                proxima_etapa = 1
            elif total_concluidas > 0:
                status = "in_progress"
                proxima_etapa = pendentes[0]["ordem_sequencia"]
            else:
                status = "available"
                proxima_etapa = atividades_modulo[0]["ordem_sequencia"]

            resposta.append({
                **modulo,
                "total_atividades": total,
                "atividades_concluidas": total_concluidas,
                "progresso_pct": round((total_concluidas / total) * 100) if total else 0,
                "status": status,
                "proxima_etapa": proxima_etapa,
            })

        return jsonify(resposta), 200

    except Exception as erro:
        return resposta_erro(
            f"Erro ao buscar módulos: {str(erro)}",
            "MODULE_LIST_ERROR",
            500,
        )


@atividades_bp.route(
    "/modulo/<int:modulo_id>/aluno/<int:aluno_id>",
    methods=["GET"],
)
@token_obrigatorio
def carregar_atividades_modulo(modulo_id, aluno_id):
    try:
        aluno_id_autenticado, erro_acesso = validar_acesso_do_aluno(
            aluno_id
        )

        if erro_acesso:
            return erro_acesso

        aluno = buscar_aluno(aluno_id_autenticado)

        if not aluno:
            return resposta_erro(
                "Aluno não encontrado.",
                "STUDENT_NOT_FOUND",
                404,
            )

        modo_aluno = str(
            aluno.get("modo_aprendizagem") or ""
        ).strip()

        if modo_aluno not in MODOS_APRENDIZAGEM:
            return resposta_erro(
                (
                    "O aluno não possui um modo de aprendizagem "
                    "válido."
                ),
                "INVALID_LEARNING_MODE",
                422,
            )

        modulo = buscar_modulo(modulo_id)

        if not modulo:
            return resposta_erro(
                "Módulo não encontrado.",
                "MODULE_NOT_FOUND",
                404,
            )

        if not modulo.get("ativo", False):
            return resposta_erro(
                "Este módulo não está disponível.",
                "MODULE_NOT_ACTIVE",
                403,
            )

        atividades_resultado = (
            supabase
            .table("atividades")
            .select(
                "id, modulo_id, palavra_chave, ordem_sequencia"
            )
            .eq("modulo_id", modulo_id)
            .order("ordem_sequencia")
            .execute()
        )

        atividades = atividades_resultado.data or []

        if not atividades:
            return resposta_erro(
                "Este módulo ainda não possui atividades.",
                "MODULE_WITHOUT_ACTIVITIES",
                404,
            )

        ids_atividades = [
            atividade["id"]
            for atividade in atividades
        ]

        variacoes_resultado = (
            supabase
            .table("variacoes_atividades")
            .select(
                (
                    "atividade_id, modo_alvo, instrucao_lex, "
                    "url_midia_padrao, tipo_interacao, "
                    "resposta_correta"
                )
            )
            .in_("atividade_id", ids_atividades)
            .eq("modo_alvo", modo_aluno)
            .execute()
        )

        variacoes = variacoes_resultado.data or []

        variacoes_por_atividade = {
            variacao["atividade_id"]: variacao
            for variacao in variacoes
        }

        ids_sem_variacao = [
            atividade["id"]
            for atividade in atividades
            if atividade["id"] not in variacoes_por_atividade
        ]

        if ids_sem_variacao:
            return jsonify({
                "erro": (
                    "Existem atividades sem variação para o "
                    f"modo '{modo_aluno}'."
                ),
                "code": "ACTIVITY_VARIATION_NOT_FOUND",
                "details": {
                    "modo_aprendizagem": modo_aluno,
                    "atividades_sem_variacao": ids_sem_variacao,
                },
            }), 422

        itens_modulo = buscar_itens_modulo(
            modulo_id
        )

        if not itens_modulo:
            return resposta_erro(
                (
                    "Este módulo ainda não possui itens "
                    "de vocabulário."
                ),
                "MODULE_WITHOUT_ITEMS",
                422,
            )

        (
            itens_normalizados,
            itens_invalidos,
        ) = normalizar_itens_modulo(
            itens_modulo
        )

        if itens_invalidos:
            return jsonify({
                "erro": (
                    "Existem itens de vocabulário "
                    "incompletos neste módulo."
                ),
                "code": "INVALID_MODULE_ITEMS",
                "details": {
                    "itens_invalidos": itens_invalidos,
                },
            }), 422

        personalizacoes_resultado = (
            supabase
            .table("personalizacao_aluno")
            .select("atividade_id, url_foto_real")
            .eq("aluno_id", aluno_id_autenticado)
            .in_("atividade_id", ids_atividades)
            .execute()
        )

        personalizacoes = (
            personalizacoes_resultado.data or []
        )

        fotos_por_atividade = {
            personalizacao["atividade_id"]:
                personalizacao["url_foto_real"]
            for personalizacao in personalizacoes
        }

        atividades_adaptadas = []

        for atividade in atividades:
            atividade_id = atividade["id"]
            variacao = variacoes_por_atividade[atividade_id]

            tipo_interacao = str(
                variacao.get("tipo_interacao") or ""
            ).strip()

            if tipo_interacao not in TIPOS_INTERACAO:
                return resposta_erro(
                    (
                        f"A atividade {atividade_id} possui um "
                        "tipo de interação inválido."
                    ),
                    "INVALID_INTERACTION_TYPE",
                    422,
                )

            midia_personalizada = fotos_por_atividade.get(
                atividade_id
            )

            midia_padrao = variacao.get(
                "url_midia_padrao"
            )

            atividades_adaptadas.append({
                "atividade_id": atividade_id,
                "palavra_chave": str(
                    atividade.get("palavra_chave") or ""
                ).strip(),
                "ordem_sequencia": atividade[
                    "ordem_sequencia"
                ],
                "modo_alvo": modo_aluno,
                "instrucao_lex": str(
                    variacao.get("instrucao_lex") or ""
                ).strip(),
                "tipo_interacao": tipo_interacao,
                "resposta_correta": str(
                    variacao.get("resposta_correta") or ""
                ).strip(),
                "url_midia": (
                    midia_personalizada or midia_padrao
                ),
                "is_personalizada": bool(
                    midia_personalizada
                ),
            })

        return jsonify({
            "aluno": {
                "id": aluno["id"],
                "nome": aluno["nome"],
                "modo_aprendizagem": modo_aluno,
                "xp_total": aluno.get("xp_total") or 0,
            },
            "modulo": {
                "id": modulo["id"],
                "nome": modulo["nome"],
            },
            "atividades": atividades_adaptadas,
            "itens": itens_normalizados,
        }), 200

    except Exception as erro:
        return resposta_erro(
            (
                "Erro ao carregar atividades adaptadas: "
                f"{str(erro)}"
            ),
            "ACTIVITY_LOAD_ERROR",
            500,
        )


@atividades_bp.route("/progresso", methods=["POST"])
@token_obrigatorio
def registrar_progresso():
    try:
        aluno_id = obter_aluno_autenticado()

        if not aluno_id:
            return resposta_erro(
                "Acesso permitido apenas para alunos.",
                "STUDENT_ACCESS_REQUIRED",
                403,
            )

        dados = request.get_json(silent=True)

        if not isinstance(dados, dict):
            return resposta_erro(
                "O corpo da requisição deve ser um JSON válido.",
                "INVALID_JSON_BODY",
                400,
            )

        aluno_id_informado = dados.get("aluno_id")

        if aluno_id_informado is not None:
            try:
                aluno_id_informado = int(
                    aluno_id_informado
                )
            except (TypeError, ValueError):
                return resposta_erro(
                    "O campo 'aluno_id' é inválido.",
                    "INVALID_STUDENT_ID",
                    400,
                )

            if aluno_id_informado != aluno_id:
                return resposta_erro(
                    (
                        "Você não pode registrar progresso "
                        "para outro aluno."
                    ),
                    "PROGRESS_ACCESS_DENIED",
                    403,
                )

        try:
            atividade_id = converter_inteiro(
                dados.get("atividade_id"),
                "atividade_id",
                minimo=1,
            )

            quantidade_erros = converter_inteiro(
                dados.get("quantidade_erros", 0),
                "quantidade_erros",
                minimo=0,
                maximo=MAXIMO_ERROS,
            )

            tempo_segundos = converter_inteiro(
                dados.get("tempo_segundos", 0),
                "tempo_segundos",
                minimo=0,
                maximo=MAXIMO_TEMPO_SEGUNDOS,
            )

            concluido = converter_booleano(
                dados.get("concluido", True),
                "concluido",
            )

        except ValueError as erro_validacao:
            return resposta_erro(
                str(erro_validacao),
                "INVALID_PROGRESS_DATA",
                400,
            )

        aluno = buscar_aluno(aluno_id)

        if not aluno:
            return resposta_erro(
                "Aluno não encontrado.",
                "STUDENT_NOT_FOUND",
                404,
            )

        modo_utilizado = str(
            aluno.get("modo_aprendizagem") or ""
        ).strip()

        if modo_utilizado not in MODOS_APRENDIZAGEM:
            return resposta_erro(
                (
                    "O aluno não possui um modo de "
                    "aprendizagem válido."
                ),
                "INVALID_LEARNING_MODE",
                422,
            )

        atividade_resultado = (
            supabase
            .table("atividades")
            .select("id")
            .eq("id", atividade_id)
            .execute()
        )

        if not atividade_resultado.data:
            return resposta_erro(
                "Atividade não encontrada.",
                "ACTIVITY_NOT_FOUND",
                404,
            )

        conclusao_anterior = (
            supabase
            .table("historico_desempenho")
            .select("id")
            .eq("aluno_id", aluno_id)
            .eq("atividade_id", atividade_id)
            .eq("concluido", True)
            .limit(1)
            .execute()
        )

        primeira_conclusao = (
            concluido and
            not conclusao_anterior.data
        )

        historico_payload = {
            "aluno_id": aluno_id,
            "atividade_id": atividade_id,
            "modo_utilizado": modo_utilizado,
            "quantidade_erros": quantidade_erros,
            "tempo_segundos": tempo_segundos,
            "concluido": concluido,
        }

        (
            supabase
            .table("historico_desempenho")
            .insert(historico_payload)
            .execute()
        )

        xp_ganho = 0

        if primeira_conclusao:
            xp_ganho = calcular_xp(quantidade_erros)
            xp_atual = converter_inteiro(
                aluno.get("xp_total") or 0,
                "xp_total",
                minimo=0,
            )

            (
                supabase
                .table("alunos")
                .update({
                    "xp_total": xp_atual + xp_ganho,
                })
                .eq("id", aluno_id)
                .execute()
            )

        return jsonify({
            "mensagem": "Progresso registrado com sucesso.",
            "code": "PROGRESS_REGISTERED",
            "data": {
                "aluno_id": aluno_id,
                "atividade_id": atividade_id,
                "concluido": concluido,
                "primeira_conclusao": primeira_conclusao,
                "xp_ganho": xp_ganho,
                "xp_total": (
                    (aluno.get("xp_total") or 0) +
                    xp_ganho
                ),
            },
        }), 201

    except Exception as erro:
        return resposta_erro(
            (
                "Erro ao salvar histórico de desempenho: "
                f"{str(erro)}"
            ),
            "PROGRESS_SAVE_ERROR",
            500,
        )
