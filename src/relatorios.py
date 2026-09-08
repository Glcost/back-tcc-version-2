from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

from flask import Blueprint, current_app, jsonify, request

from auth import token_obrigatorio
from src.bd_config import supabase, supabase_admin


relatorios_bp = Blueprint(
    "relatorios",
    __name__,
)

# Os relatórios precisam realizar consultas agregadas.
# A autorização continua sendo validada pela aplicação antes
# de qualquer consulta que utilize o cliente administrativo.
_db = supabase_admin if supabase_admin else supabase


# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def _resposta_erro(mensagem, codigo, status):
    return jsonify({
        "erro": mensagem,
        "code": codigo,
    }), status


def _numero(valor, padrao=0):
    if valor is None:
        return padrao

    try:
        return float(valor)
    except (TypeError, ValueError):
        return padrao


def _inteiro(valor, padrao=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _media(valores, casas=2):
    numeros = [
        _numero(valor)
        for valor in valores
        if valor is not None
    ]

    return (
        round(mean(numeros), casas)
        if numeros
        else 0
    )


def _percentual(parte, total, casas=1):
    if not total:
        return 0

    return round(
        (parte / total) * 100,
        casas,
    )


def _perfil_autenticado():
    usuario = getattr(
        request,
        "usuario_logado",
        {},
    ) or {}

    return usuario.get("perfil")


def _aluno_autenticado_id():
    return _inteiro(
        getattr(request, "aluno_id", None),
        None,
    )


def _professor_autenticado_id():
    return _inteiro(
        getattr(request, "professor_id", None),
        None,
    )


def _normalizar_data(data_hora):
    if not data_hora:
        return None

    return str(data_hora).strip()


def _extrair_dia(data_hora):
    data_normalizada = _normalizar_data(
        data_hora
    )

    if not data_normalizada:
        return "sem_data"

    return data_normalizada[:10]


def _ordenar_por_data(registro):
    data_hora = registro.get("data_hora")

    if not data_hora:
        return ""

    return str(data_hora)


# ============================================================
# AUTORIZAÇÃO
# ============================================================

def _validar_professor(professor_id):
    professor_token_id = (
        _professor_autenticado_id()
    )

    if not professor_token_id:
        return _resposta_erro(
            (
                "Acesso permitido apenas para "
                "professores."
            ),
            "TEACHER_ACCESS_REQUIRED",
            403,
        )

    if professor_token_id != professor_id:
        return _resposta_erro(
            (
                "Você não pode acessar o dashboard "
                "de outro professor."
            ),
            "TEACHER_ACCESS_DENIED",
            403,
        )

    return None


def _professor_possui_aluno(
    professor_id,
    aluno_id,
):
    resultado = (
        _db
        .table("alunos")
        .select("id")
        .eq("id", aluno_id)
        .eq("professor_id", professor_id)
        .limit(1)
        .execute()
    )

    return bool(resultado.data)


def _validar_acesso_ao_aluno(aluno_id):
    perfil = _perfil_autenticado()

    if perfil == "aluno":
        aluno_token_id = (
            _aluno_autenticado_id()
        )

        if aluno_token_id != aluno_id:
            return _resposta_erro(
                (
                    "Você não pode acessar o relatório "
                    "de outro aluno."
                ),
                "STUDENT_REPORT_ACCESS_DENIED",
                403,
            )

        return None

    if perfil == "professor":
        professor_id = (
            _professor_autenticado_id()
        )

        if (
            not professor_id
            or not _professor_possui_aluno(
                professor_id,
                aluno_id,
            )
        ):
            return _resposta_erro(
                (
                    "Este aluno não está vinculado "
                    "ao professor autenticado."
                ),
                "STUDENT_NOT_ASSIGNED_TO_TEACHER",
                403,
            )

        return None

    return _resposta_erro(
        "Perfil sem permissão para acessar relatórios.",
        "REPORT_ACCESS_DENIED",
        403,
    )


# ============================================================
# CONSULTAS COMPARTILHADAS
# ============================================================

def _buscar_aluno(aluno_id):
    resultado = (
        _db
        .table("alunos")
        .select(
            (
                "id, professor_id, nome, ano_escolar, "
                "modo_aprendizagem, xp_total"
            )
        )
        .eq("id", aluno_id)
        .limit(1)
        .execute()
    )

    if not resultado.data:
        return None

    return resultado.data[0]


def _buscar_alunos_professor(professor_id):
    resultado = (
        _db
        .table("alunos")
        .select(
            (
                "id, professor_id, nome, "
                "ano_escolar, modo_aprendizagem, "
                "xp_total"
            )
        )
        .eq("professor_id", professor_id)
        .order("nome")
        .execute()
    )

    return resultado.data or []


def _buscar_historico_alunos(ids_alunos):
    if not ids_alunos:
        return []

    resultado = (
        _db
        .table("historico_desempenho")
        .select(
            (
                "id, aluno_id, atividade_id, "
                "modo_utilizado, quantidade_erros, "
                "tempo_segundos, concluido, data_hora"
            )
        )
        .in_("aluno_id", ids_alunos)
        .order("data_hora")
        .execute()
    )

    return resultado.data or []


def _buscar_historico_aluno(aluno_id):
    resultado = (
        _db
        .table("historico_desempenho")
        .select(
            (
                "id, aluno_id, atividade_id, "
                "modo_utilizado, quantidade_erros, "
                "tempo_segundos, concluido, data_hora"
            )
        )
        .eq("aluno_id", aluno_id)
        .order("data_hora")
        .execute()
    )

    return resultado.data or []


def _buscar_atividades(ids_atividades):
    if not ids_atividades:
        return []

    resultado = (
        _db
        .table("atividades")
        .select(
            (
                "id, modulo_id, palavra_chave, "
                "ordem_sequencia"
            )
        )
        .in_("id", ids_atividades)
        .execute()
    )

    return resultado.data or []


def _buscar_modulos(ids_modulos):
    if not ids_modulos:
        return []

    resultado = (
        _db
        .table("modulos")
        .select("id, nome, ativo")
        .in_("id", ids_modulos)
        .execute()
    )

    return resultado.data or []


def _enriquecer_historico(historico):
    ids_atividades = list({
        registro.get("atividade_id")
        for registro in historico
        if registro.get("atividade_id")
    })

    atividades = _buscar_atividades(
        ids_atividades
    )

    atividades_por_id = {
        atividade["id"]: atividade
        for atividade in atividades
    }

    ids_modulos = list({
        atividade.get("modulo_id")
        for atividade in atividades
        if atividade.get("modulo_id")
    })

    modulos = _buscar_modulos(
        ids_modulos
    )

    modulos_por_id = {
        modulo["id"]: modulo
        for modulo in modulos
    }

    historico_enriquecido = []

    for registro in historico:
        atividade = atividades_por_id.get(
            registro.get("atividade_id"),
            {},
        )

        modulo = modulos_por_id.get(
            atividade.get("modulo_id"),
            {},
        )

        historico_enriquecido.append({
            "id": registro.get("id"),
            "aluno_id": registro.get("aluno_id"),
            "atividade_id": registro.get(
                "atividade_id"
            ),
            "modo_utilizado": registro.get(
                "modo_utilizado"
            ),
            "quantidade_erros": _inteiro(
                registro.get("quantidade_erros")
            ),
            "tempo_segundos": _inteiro(
                registro.get("tempo_segundos")
            ),
            "concluido": bool(
                registro.get("concluido")
            ),
            "data_hora": _normalizar_data(
                registro.get("data_hora")
            ),
            "atividade": {
                "id": atividade.get("id"),
                "palavra_chave": atividade.get(
                    "palavra_chave"
                ),
                "ordem_sequencia": atividade.get(
                    "ordem_sequencia"
                ),
            },
            "modulo": {
                "id": modulo.get("id"),
                "nome": modulo.get("nome"),
            },
        })

    return sorted(
        historico_enriquecido,
        key=_ordenar_por_data,
    )


# ============================================================
# CÁLCULO DE MÉTRICAS
# ============================================================

def _calcular_resumo(historico):
    tentadas_ids = {
        registro.get("atividade_id")
        for registro in historico
        if registro.get("atividade_id")
    }

    concluidas_ids = {
        registro.get("atividade_id")
        for registro in historico
        if (
            registro.get("atividade_id")
            and registro.get("concluido")
        )
    }

    registros_concluidos = [
        registro
        for registro in historico
        if registro.get("concluido")
    ]

    total_erros = sum(
        _inteiro(
            registro.get("quantidade_erros")
        )
        for registro in historico
    )

    tempo_total = sum(
        _inteiro(
            registro.get("tempo_segundos")
        )
        for registro in historico
    )

    return {
        # Quantidade total de tentativas registradas.
        "tentativas_totais": len(historico),

        # Quantidade de atividades únicas tentadas.
        "atividades_tentadas": len(
            tentadas_ids
        ),

        # Quantidade de atividades únicas concluídas.
        "atividades_concluidas": len(
            concluidas_ids
        ),

        "conclusoes_registradas": len(
            registros_concluidos
        ),

        "taxa_conclusao_pct": _percentual(
            len(concluidas_ids),
            len(tentadas_ids),
        ),

        "total_erros": total_erros,

        "media_erros": _media([
            registro.get("quantidade_erros")
            for registro in historico
        ]),

        "tempo_total_segundos": tempo_total,

        "media_tempo_segundos": _media([
            registro.get("tempo_segundos")
            for registro in historico
        ]),
    }


def _calcular_evolucao_diaria(historico):
    evolucao_por_dia = defaultdict(
        lambda: {
            "tentativas": 0,
            "conclusoes": 0,
            "atividades_tentadas": set(),
            "atividades_concluidas": set(),
            "erros": [],
            "tempos": [],
        }
    )

    for registro in historico:
        dia = _extrair_dia(
            registro.get("data_hora")
        )

        atividade_id = registro.get(
            "atividade_id"
        )

        dados_dia = evolucao_por_dia[dia]

        dados_dia["tentativas"] += 1

        if atividade_id:
            dados_dia[
                "atividades_tentadas"
            ].add(atividade_id)

        dados_dia["erros"].append(
            registro.get("quantidade_erros")
        )

        dados_dia["tempos"].append(
            registro.get("tempo_segundos")
        )

        if registro.get("concluido"):
            dados_dia["conclusoes"] += 1

            if atividade_id:
                dados_dia[
                    "atividades_concluidas"
                ].add(atividade_id)

    evolucao = []

    for dia, dados in sorted(
        evolucao_por_dia.items()
    ):
        evolucao.append({
            "data": dia,
            "tentativas": dados["tentativas"],
            "conclusoes": dados["conclusoes"],
            "atividades_tentadas": len(
                dados["atividades_tentadas"]
            ),
            "atividades_concluidas": len(
                dados["atividades_concluidas"]
            ),
            "media_erros": _media(
                dados["erros"]
            ),
            "media_tempo_segundos": _media(
                dados["tempos"]
            ),
        })

    return evolucao


def _calcular_desempenho_modulos(
    historico_enriquecido,
):
    por_modulo = defaultdict(list)

    for registro in historico_enriquecido:
        modulo = registro.get("modulo") or {}
        modulo_id = modulo.get("id")

        if modulo_id:
            por_modulo[modulo_id].append(
                registro
            )

    desempenho = []

    for modulo_id, registros in por_modulo.items():
        modulo = registros[0].get(
            "modulo",
            {},
        )

        resumo = _calcular_resumo(
            registros
        )

        desempenho.append({
            "modulo_id": modulo_id,
            "nome": (
                modulo.get("nome")
                or "Módulo sem nome"
            ),
            **resumo,
        })

    return sorted(
        desempenho,
        key=lambda item: item["nome"],
    )


def _ultimo_acesso(historico):
    datas = [
        registro.get("data_hora")
        for registro in historico
        if registro.get("data_hora")
    ]

    return max(datas) if datas else None


# ============================================================
# 1. VISÃO GERAL GLOBAL
# ============================================================

@relatorios_bp.route(
    "/visao-geral",
    methods=["GET"],
)
@token_obrigatorio
def visao_geral():
    """
    A visão global contém dados de toda a plataforma.
    Somente um futuro perfil administrativo poderá acessá-la.
    """

    if _perfil_autenticado() != "admin":
        return _resposta_erro(
            (
                "A visão geral da plataforma é restrita "
                "a administradores."
            ),
            "ADMIN_ACCESS_REQUIRED",
            403,
        )

    try:
        alunos = (
            _db
            .table("alunos")
            .select(
                "id, modo_aprendizagem, xp_total"
            )
            .execute()
            .data
            or []
        )

        professores = (
            _db
            .table("professores")
            .select("id")
            .execute()
            .data
            or []
        )

        modulos = (
            _db
            .table("modulos")
            .select("id, ativo")
            .execute()
            .data
            or []
        )

        historico = (
            _db
            .table("historico_desempenho")
            .select(
                (
                    "atividade_id, quantidade_erros, "
                    "tempo_segundos, concluido"
                )
            )
            .execute()
            .data
            or []
        )

        resumo = _calcular_resumo(
            historico
        )

        distribuicao_modo = Counter(
            aluno.get("modo_aprendizagem")
            or "Não definido"
            for aluno in alunos
        )

        return jsonify({
            "totais": {
                "alunos": len(alunos),
                "professores": len(professores),
                "modulos_ativos": len([
                    modulo
                    for modulo in modulos
                    if modulo.get("ativo")
                ]),
                "tentativas_registradas": resumo[
                    "tentativas_totais"
                ],
                "atividades_concluidas": resumo[
                    "atividades_concluidas"
                ],
            },
            "resumo": resumo,
            "media_xp_por_aluno": _media([
                aluno.get("xp_total")
                for aluno in alunos
            ]),
            "distribuicao_modo_aprendizagem": dict(
                distribuicao_modo
            ),
        }), 200

    except Exception:
        current_app.logger.exception(
            "Erro ao gerar visão geral."
        )

        return _resposta_erro(
            "Não foi possível gerar a visão geral.",
            "OVERVIEW_REPORT_ERROR",
            500,
        )


# ============================================================
# 2. DASHBOARD DO PROFESSOR
# ============================================================

@relatorios_bp.route(
    "/professor/<int:professor_id>",
    methods=["GET"],
)
@token_obrigatorio
def relatorio_professor(professor_id):
    erro_acesso = _validar_professor(
        professor_id
    )

    if erro_acesso:
        return erro_acesso

    try:
        alunos = _buscar_alunos_professor(
            professor_id
        )

        if not alunos:
            return jsonify({
                "professor_id": professor_id,
                "total_alunos": 0,
                "distribuicao_modo_aprendizagem": {},
                "ranking_xp": [],
                "alunos_com_possivel_dificuldade": [],
                "alunos": [],
            }), 200

        ids_alunos = [
            aluno["id"]
            for aluno in alunos
        ]

        historico = _buscar_historico_alunos(
            ids_alunos
        )

        historico_por_aluno = defaultdict(list)

        for registro in historico:
            historico_por_aluno[
                registro["aluno_id"]
            ].append(registro)

        alunos_detalhados = []

        for aluno in alunos:
            registros = historico_por_aluno.get(
                aluno["id"],
                [],
            )

            resumo = _calcular_resumo(
                registros
            )

            alunos_detalhados.append({
                "aluno_id": aluno["id"],
                "nome": aluno["nome"],
                "ano_escolar": aluno.get(
                    "ano_escolar"
                ),
                "modo_aprendizagem": aluno.get(
                    "modo_aprendizagem"
                ),
                "xp_total": _inteiro(
                    aluno.get("xp_total")
                ),
                "ultimo_acesso": _ultimo_acesso(
                    registros
                ),
                **resumo,
            })

        ranking_xp = sorted(
            alunos_detalhados,
            key=lambda aluno: aluno["xp_total"],
            reverse=True,
        )

        alunos_com_tentativas = [
            aluno
            for aluno in alunos_detalhados
            if aluno["tentativas_totais"] > 0
        ]

        possivel_dificuldade = sorted(
            alunos_com_tentativas,
            key=lambda aluno: (
                aluno["media_erros"],
                -aluno["taxa_conclusao_pct"],
            ),
            reverse=True,
        )[:5]

        distribuicao_modo = Counter(
            aluno.get("modo_aprendizagem")
            or "Não definido"
            for aluno in alunos
        )

        return jsonify({
            "professor_id": professor_id,
            "total_alunos": len(alunos),
            "distribuicao_modo_aprendizagem": dict(
                distribuicao_modo
            ),
            "total_tentativas": len(historico),
            "total_atividades_concluidas": sum(
                aluno["atividades_concluidas"]
                for aluno in alunos_detalhados
            ),
            "media_erros_turma": _media([
                aluno["media_erros"]
                for aluno in alunos_com_tentativas
            ]),
            "media_tempo_turma_segundos": _media([
                aluno["media_tempo_segundos"]
                for aluno in alunos_com_tentativas
            ]),
            "ranking_xp": ranking_xp,
            "alunos_com_possivel_dificuldade":
                possivel_dificuldade,
            "alunos": alunos_detalhados,
        }), 200

    except Exception:
        current_app.logger.exception(
            "Erro ao gerar relatório do professor."
        )

        return _resposta_erro(
            (
                "Não foi possível gerar o relatório "
                "do professor."
            ),
            "TEACHER_REPORT_ERROR",
            500,
        )


# ============================================================
# 3. RELATÓRIO INDIVIDUAL DO ALUNO
# ============================================================

@relatorios_bp.route(
    "/aluno/<int:aluno_id>",
    methods=["GET"],
)
@token_obrigatorio
def relatorio_aluno(aluno_id):
    try:
        erro_acesso = _validar_acesso_ao_aluno(
            aluno_id
        )

        if erro_acesso:
            return erro_acesso

        aluno = _buscar_aluno(
            aluno_id
        )

        if not aluno:
            return _resposta_erro(
                "Aluno não encontrado.",
                "STUDENT_NOT_FOUND",
                404,
            )

        historico = _buscar_historico_aluno(
            aluno_id
        )

        historico_enriquecido = (
            _enriquecer_historico(
                historico
            )
        )

        resumo = _calcular_resumo(
            historico
        )

        return jsonify({
            "aluno": {
                "id": aluno["id"],
                "nome": aluno["nome"],
                "ano_escolar": aluno.get(
                    "ano_escolar"
                ),
                "modo_aprendizagem": aluno.get(
                    "modo_aprendizagem"
                ),
                "xp_total": _inteiro(
                    aluno.get("xp_total")
                ),
            },
            "resumo": resumo,
            "evolucao_diaria":
                _calcular_evolucao_diaria(
                    historico
                ),
            "desempenho_modulos":
                _calcular_desempenho_modulos(
                    historico_enriquecido
                ),
            "historico": list(
                reversed(
                    historico_enriquecido
                )
            ),
        }), 200

    except Exception:
        current_app.logger.exception(
            "Erro ao gerar relatório do aluno."
        )

        return _resposta_erro(
            (
                "Não foi possível gerar o relatório "
                "do aluno."
            ),
            "STUDENT_REPORT_ERROR",
            500,
        )


# ============================================================
# 4. RELATÓRIO POR MÓDULO DO PROFESSOR
# ============================================================

@relatorios_bp.route(
    "/modulo/<int:modulo_id>",
    methods=["GET"],
)
@token_obrigatorio
def relatorio_modulo(modulo_id):
    professor_id = (
        _professor_autenticado_id()
    )

    if not professor_id:
        return _resposta_erro(
            (
                "Acesso permitido apenas para "
                "professores."
            ),
            "TEACHER_ACCESS_REQUIRED",
            403,
        )

    try:
        atividades = (
            _db
            .table("atividades")
            .select(
                (
                    "id, modulo_id, palavra_chave, "
                    "ordem_sequencia"
                )
            )
            .eq("modulo_id", modulo_id)
            .order("ordem_sequencia")
            .execute()
            .data
            or []
        )

        if not atividades:
            return _resposta_erro(
                (
                    "Nenhuma atividade encontrada "
                    "para este módulo."
                ),
                "MODULE_WITHOUT_ACTIVITIES",
                404,
            )

        alunos = _buscar_alunos_professor(
            professor_id
        )

        ids_alunos = [
            aluno["id"]
            for aluno in alunos
        ]

        if not ids_alunos:
            return jsonify({
                "modulo_id": modulo_id,
                "total_atividades": len(
                    atividades
                ),
                "alunos_participantes_modulo": 0,
                "alunos_concluiram_modulo": 0,
                "atividades": [],
                "atividades_mais_dificeis": [],
            }), 200

        ids_atividades = [
            atividade["id"]
            for atividade in atividades
        ]

        historico = (
            _db
            .table("historico_desempenho")
            .select(
                (
                    "aluno_id, atividade_id, "
                    "quantidade_erros, "
                    "tempo_segundos, concluido"
                )
            )
            .in_("aluno_id", ids_alunos)
            .in_(
                "atividade_id",
                ids_atividades,
            )
            .execute()
            .data
            or []
        )

        historico_por_atividade = defaultdict(
            list
        )
        atividades_concluidas_por_aluno = (
            defaultdict(set)
        )
        alunos_participantes_modulo = set()

        for registro in historico:
            historico_por_atividade[
                registro["atividade_id"]
            ].append(registro)
            alunos_participantes_modulo.add(
                registro["aluno_id"]
            )

            if registro.get("concluido"):
                atividades_concluidas_por_aluno[
                    registro["aluno_id"]
                ].add(
                    registro["atividade_id"]
                )

        detalhes = []

        for atividade in atividades:
            registros = (
                historico_por_atividade.get(
                    atividade["id"],
                    [],
                )
            )

            resumo = _calcular_resumo(
                registros
            )

            detalhes.append({
                "atividade_id": atividade["id"],
                "palavra_chave": atividade[
                    "palavra_chave"
                ],
                "ordem": atividade[
                    "ordem_sequencia"
                ],
                "alunos_participantes": len({
                    registro["aluno_id"]
                    for registro in registros
                }),
                **resumo,
            })

        mais_dificeis = sorted(
            [
                detalhe
                for detalhe in detalhes
                if detalhe["tentativas_totais"] > 0
            ],
            key=lambda detalhe: (
                detalhe["media_erros"],
                -detalhe["taxa_conclusao_pct"],
            ),
            reverse=True,
        )[:5]

        return jsonify({
            "modulo_id": modulo_id,
            "total_atividades": len(
                atividades
            ),
            "alunos_participantes_modulo": len(
                alunos_participantes_modulo
            ),
            "alunos_concluiram_modulo": sum(
                1
                for atividades_concluidas
                in atividades_concluidas_por_aluno.values()
                if set(ids_atividades).issubset(
                    atividades_concluidas
                )
            ),
            "atividades": detalhes,
            "atividades_mais_dificeis":
                mais_dificeis,
        }), 200

    except Exception:
        current_app.logger.exception(
            "Erro ao gerar relatório do módulo."
        )

        return _resposta_erro(
            (
                "Não foi possível gerar o relatório "
                "do módulo."
            ),
            "MODULE_REPORT_ERROR",
            500,
        )
