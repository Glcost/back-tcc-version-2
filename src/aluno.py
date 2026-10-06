from datetime import datetime, timezone, timedelta, time
from flask import Blueprint, request, jsonify, current_app
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase, supabase_admin

alunos_bp = Blueprint('alunos', __name__)

FUSO_BRASIL = timezone(timedelta(hours=-3))


MISSOES_DIARIAS = (
    {
        "codigo": "complete_uma_atividade",
        "nome": "Complete uma atividade",
        "descricao": "Realize qualquer atividade disponível.",
        "xp": 50,
        "meta": 1,
        "tipo": "atividades",
        "icone": "fi fi-br-puzzle-pieces",
        "cor": "blue",
    },
    {
        "codigo": "complete_tres_atividades",
        "nome": "Complete três atividades",
        "descricao": "Conclua três atividades durante o dia.",
        "xp": 40,
        "meta": 3,
        "tipo": "atividades",
        "icone": "fi fi-br-check-circle",
        "cor": "green",
    },
    {
        "codigo": "estude_dez_minutos",
        "nome": "Estude por 10 minutos",
        "descricao": "Acumule pelo menos 10 minutos de estudo.",
        "xp": 30,
        "meta": 600,
        "tipo": "tempo",
        "icone": "fi fi-br-time-fast",
        "cor": "blue",
    },
    {
        "codigo": "atividade_sem_erros",
        "nome": "Conclua sem erros",
        "descricao": "Finalize uma atividade sem cometer erros.",
        "xp": 40,
        "meta": 1,
        "tipo": "sem_erros",
        "icone": "fi fi-br-badge-check",
        "cor": "green",
    },
    {
        "codigo": "ofensiva_dois_dias",
        "nome": "Mantenha sua ofensiva",
        "descricao": "Estude em dois dias consecutivos.",
        "xp": 40,
        "meta": 2,
        "tipo": "ofensiva",
        "icone": "fi fi-br-flame",
        "cor": "blue",
    },
)


def converter_data_historico(data_hora):
    """
    Converte a data do Supabase para uma data no horário de Brasília.
    Datas sem fuso horário são consideradas como UTC.
    """
    if not data_hora:
        return None

    try:
        texto_data = str(data_hora).strip()

        if texto_data.endswith("Z"):
            texto_data = texto_data[:-1] + "+00:00"

        data_convertida = datetime.fromisoformat(texto_data)

        if data_convertida.tzinfo is None:
            data_convertida = data_convertida.replace(
                tzinfo=timezone.utc
            )

        return data_convertida.astimezone(
            FUSO_BRASIL
        ).date()

    except (TypeError, ValueError):
        return None


def calcular_ofensiva(aluno_id):
    """
    Calcula quantos dias consecutivos o aluno realizou
    pelo menos uma atividade concluída.
    """
    historico_res = (
        supabase
        .table("historico_desempenho")
        .select("data_hora")
        .eq("aluno_id", aluno_id)
        .eq("concluido", True)
        .order("data_hora", desc=True)
        .execute()
    )

    dias_com_atividade = {
        dia
        for registro in (historico_res.data or [])
        if (
            dia := converter_data_historico(
                registro.get("data_hora")
            )
        )
    }

    if not dias_com_atividade:
        return 0

    hoje = datetime.now(
        FUSO_BRASIL
    ).date()

    ultimo_dia = max(dias_com_atividade)

    if ultimo_dia == hoje:
        dia_analisado = hoje
    elif ultimo_dia == hoje - timedelta(days=1):
        dia_analisado = ultimo_dia
    else:
        return 0

    ofensiva = 0

    while dia_analisado in dias_com_atividade:
        ofensiva += 1
        dia_analisado -= timedelta(days=1)

    return ofensiva



def obter_intervalo_dia_brasilia():
    """
    Retorna a data atual no Brasil e o intervalo equivalente
    em UTC para consultar o histórico do Supabase.
    """

    agora_brasil = datetime.now(FUSO_BRASIL)
    data_brasil = agora_brasil.date()

    inicio_brasil = datetime.combine(
        data_brasil,
        time.min,
        tzinfo=FUSO_BRASIL,
    )

    fim_brasil = inicio_brasil + timedelta(days=1)

    inicio_utc = (
        inicio_brasil
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat()
    )

    fim_utc = (
        fim_brasil
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat()
    )

    return data_brasil, inicio_utc, fim_utc


def buscar_aluno_para_missoes(aluno_id):
    resultado = (
        supabase
        .table("alunos")
        .select("id, nome, xp_total, ativo")
        .eq("id", aluno_id)
        .eq("ativo", True)
        .limit(1)
        .execute()
    )

    if not resultado.data:
        return None

    return resultado.data[0]


def buscar_historico_do_dia(
    aluno_id,
    inicio_utc,
    fim_utc,
):
    resultado = (
        supabase
        .table("historico_desempenho")
        .select(
            (
                "atividade_id, quantidade_erros, "
                "tempo_segundos, concluido, data_hora"
            )
        )
        .eq("aluno_id", aluno_id)
        .eq("concluido", True)
        .gte("data_hora", inicio_utc)
        .lt("data_hora", fim_utc)
        .order("data_hora")
        .execute()
    )

    return resultado.data or []


def buscar_recompensas_recebidas(
    aluno_id,
    data_missao,
):
    if supabase_admin is None:
        raise RuntimeError(
            "O cliente administrativo do Supabase "
            "não está configurado."
        )

    resultado = (
        supabase_admin
        .table("recompensas_missoes")
        .select(
            "missao_codigo, xp_recebido, recebido_em"
        )
        .eq("aluno_id", aluno_id)
        .eq("data_missao", data_missao.isoformat())
        .execute()
    )

    recompensas = {}

    for registro in resultado.data or []:
        codigo = registro.get("missao_codigo")

        if codigo:
            recompensas[codigo] = registro

    return recompensas


def calcular_metricas_diarias(
    historico,
    ofensiva,
):
    atividades_ids = {
        registro.get("atividade_id")
        for registro in historico
        if registro.get("atividade_id") is not None
    }

    atividades_concluidas = len(atividades_ids)

    tempo_total = sum(
        max(
            0,
            int(registro.get("tempo_segundos") or 0),
        )
        for registro in historico
    )

    atividades_sem_erros = sum(
        1
        for registro in historico
        if int(
            registro.get("quantidade_erros") or 0
        ) == 0
    )

    return {
        "atividades": atividades_concluidas,
        "tempo": tempo_total,
        "sem_erros": atividades_sem_erros,
        "ofensiva": ofensiva,
    }


def obter_progresso_missao(
    missao,
    metricas,
):
    tipo = missao["tipo"]
    progresso = int(metricas.get(tipo, 0) or 0)
    meta = missao["meta"]

    return min(progresso, meta)


def montar_missoes_do_dia(
    metricas,
    recompensas_recebidas,
):
    missoes = []

    for configuracao in MISSOES_DIARIAS:
        codigo = configuracao["codigo"]
        progresso = obter_progresso_missao(
            configuracao,
            metricas,
        )

        concluida = progresso >= configuracao["meta"]
        recompensa = recompensas_recebidas.get(codigo)
        recompensa_recebida = recompensa is not None

        missoes.append({
            "codigo": codigo,
            "nome": configuracao["nome"],
            "descricao": configuracao["descricao"],
            "icone": configuracao["icone"],
            "cor": configuracao["cor"],
            "xp": configuracao["xp"],
            "progresso": progresso,
            "meta": configuracao["meta"],
            "tipo": configuracao["tipo"],
            "concluida": concluida,
            "recompensa_recebida": recompensa_recebida,
            "recompensa_disponivel": (
                concluida and not recompensa_recebida
            ),
            "recebido_em": (
                recompensa.get("recebido_em")
                if recompensa
                else None
            ),
        })

    return missoes


def criar_resumo_missoes(missoes):
    concluidas = sum(
        1
        for missao in missoes
        if missao["concluida"]
    )

    recompensas_recebidas = sum(
        1
        for missao in missoes
        if missao["recompensa_recebida"]
    )

    xp_recebido = sum(
        missao["xp"]
        for missao in missoes
        if missao["recompensa_recebida"]
    )

    xp_disponivel = sum(
        missao["xp"]
        for missao in missoes
        if missao["recompensa_disponivel"]
    )

    total = len(missoes)

    progresso_pct = (
        round((concluidas / total) * 100, 1)
        if total
        else 0
    )

    return {
        "concluidas": concluidas,
        "total": total,
        "progresso_pct": progresso_pct,
        "recompensas_recebidas": recompensas_recebidas,
        "xp_recebido": xp_recebido,
        "xp_disponivel": xp_disponivel,
        "xp_total_possivel": sum(
            missao["xp"]
            for missao in missoes
        ),
    }


def carregar_missoes_aluno(aluno_id):
    aluno = buscar_aluno_para_missoes(aluno_id)

    if not aluno:
        return None

    (
        data_missao,
        inicio_utc,
        fim_utc,
    ) = obter_intervalo_dia_brasilia()

    historico = buscar_historico_do_dia(
        aluno_id,
        inicio_utc,
        fim_utc,
    )

    ofensiva = calcular_ofensiva(aluno_id)

    recompensas = buscar_recompensas_recebidas(
        aluno_id,
        data_missao,
    )

    metricas = calcular_metricas_diarias(
        historico,
        ofensiva,
    )

    missoes = montar_missoes_do_dia(
        metricas,
        recompensas,
    )

    return {
        "data": data_missao.isoformat(),
        "fuso_horario": "America/Sao_Paulo",
        "aluno": {
            "id": aluno["id"],
            "nome": aluno["nome"],
            "xp_total": int(
                aluno.get("xp_total") or 0
            ),
        },
        "resumo": criar_resumo_missoes(missoes),
        "missoes": missoes,
    }


def localizar_configuracao_missao(codigo):
    codigo_normalizado = str(codigo or "").strip()

    for missao in MISSOES_DIARIAS:
        if missao["codigo"] == codigo_normalizado:
            return missao

    return None

@alunos_bp.route('/login', methods=['POST'])
def login_aluno():
    try: 
        dados = request.get_json(silent=True) or {}

        # Aceita 'pin' ou 'pin_acesso' para manter compatibilidade com o contrato do frontend
        pin = dados.get('pin') or dados.get('pin_acesso')
        email = dados.get('email')

        if not pin or not email:
            return jsonify({"erro": "Os campos 'email' e 'pin' são obrigatórios.", "code": "MISSING_FIELDS"}), 400

        pin_digitado = str(pin).strip()
        email_limpo = str(email).strip().lower()

        busca = supabase.table('alunos').select('*').eq('pin_acesso', pin_digitado).eq('email', email_limpo).eq("ativo", True).execute()

        if not busca.data or len(busca.data) == 0:
            return jsonify({"erro": "E-mail ou PIN de acesso inválido.", "code": "INVALID_CREDENTIALS"}), 401
            
        aluno = busca.data[0]
        
        # Emite token JWT com perfil de aluno
        token = gerar_token({"id": aluno['id'], "nome": aluno['nome']}, perfil="aluno")

        return jsonify({
            "mensagem": "Login efetuado com sucesso!",
            "token": token,
            "role": "student",
            "user": {
                "id": aluno['id'],
                "name": aluno['nome'],
                "email": aluno['email'],
                "schoolYear": aluno.get('ano_escolar'),
                "supportLevel": aluno.get('modo_aprendizagem')
            }
        }), 200

    except Exception as e:
        return jsonify({"erro": f"Erro interno durante a autenticação do aluno: {str(e)}"}), 500


@alunos_bp.route('/me', methods=['GET'])
@token_obrigatorio
def obter_aluno_atual():
    """
    Retorna os dados do aluno autenticado com base no token JWT.
    """
    try:
        aluno_id = request.aluno_id
        if not aluno_id:
            return jsonify({"erro": "Acesso permitido apenas para estudantes.", "code": "FORBIDDEN"}), 403

        aluno_res = ( supabase.table("alunos").select("*").eq("id", aluno_id).eq("ativo", True).maybe_single().execute()
            )
        
        if not aluno_res.data:
            return jsonify({"erro": "Estudante não encontrado.", 
                            "code": "NOT_FOUND"}), 404
                    
        aluno = aluno_res.data

        ofensiva_atual = calcular_ofensiva(aluno_id)

        return jsonify({
            "id": aluno["id"],
            "name": aluno["nome"],
            "email": aluno["email"],
            "schoolYear": aluno.get("ano_escolar"),
            "supportLevel": aluno.get("modo_aprendizagem"),
            "xpTotal": aluno.get("xp_total", 0),
            "currentStreak": ofensiva_atual
        }), 200
        

    except Exception as e:
        return jsonify({"erro": f"Falha ao carregar perfil atual: {str(e)}"}), 500


@alunos_bp.route("/missoes-do-dia",methods=["GET"],)
@token_obrigatorio
def obter_missoes_do_dia():
    try:
        aluno_id = getattr(
            request,
            "aluno_id",
            None,
        )

        if not aluno_id:
            return jsonify({
                "erro": (
                    "Acesso permitido apenas "
                    "para estudantes."
                ),
                "code": "STUDENT_ACCESS_REQUIRED",
            }), 403

        if supabase_admin is None:
            return jsonify({
                "erro": (
                    "O serviço de missões não está "
                    "configurado no servidor."
                ),
                "code": "MISSIONS_SERVICE_UNAVAILABLE",
            }), 503

        dados = carregar_missoes_aluno(
            aluno_id
        )

        if not dados:
            return jsonify({
                "erro": "Aluno não encontrado.",
                "code": "STUDENT_NOT_FOUND",
            }), 404

        return jsonify(dados), 200

    except Exception:
        current_app.logger.exception(
            "Erro ao carregar as missões do aluno."
        )

        return jsonify({
            "erro": (
                "Não foi possível carregar "
                "as missões do dia."
            ),
            "code": "DAILY_MISSIONS_LOAD_ERROR",
        }), 500
        
        
@alunos_bp.route("/missoes-do-dia/resgatar",methods=["POST"],)
@token_obrigatorio
def resgatar_recompensa_missao():
    try:
        aluno_id = getattr(request,"aluno_id",None,)
        
        if not aluno_id:
            return jsonify({
                "erro": (
                    "Acesso permitido apenas "
                    "para estudantes."
                ),
                "code": "STUDENT_ACCESS_REQUIRED",
            }), 403

        if supabase_admin is None:
            return jsonify({
                "erro": (
                    "O serviço de missões não está "
                    "configurado no servidor."
                ),
                "code": "MISSIONS_SERVICE_UNAVAILABLE",
            }), 503

        dados_requisicao = (
            request.get_json(silent=True) or {}
        )

        missao_codigo = str(
            dados_requisicao.get(
                "missao_codigo",
                "",
            )
        ).strip()

        configuracao = localizar_configuracao_missao(
            missao_codigo
        )

        if not configuracao:
            return jsonify({
                "erro": "Missão inválida.",
                "code": "INVALID_MISSION",
            }), 400

        dados_missoes = carregar_missoes_aluno(
            aluno_id
        )

        if not dados_missoes:
            return jsonify({
                "erro": "Aluno não encontrado.",
                "code": "STUDENT_NOT_FOUND",
            }), 404

        missao_atual = next(
            (
                missao
                for missao in dados_missoes["missoes"]
                if missao["codigo"] == missao_codigo
            ),
            None,
        )

        if not missao_atual:
            return jsonify({
                "erro": "Missão não encontrada.",
                "code": "MISSION_NOT_FOUND",
            }), 404

        if not missao_atual["concluida"]:
            return jsonify({
                "erro": (
                    "A meta desta missão ainda "
                    "não foi alcançada."
                ),
                "code": "MISSION_NOT_COMPLETED",
                "missao": missao_atual,
            }), 409

        if missao_atual["recompensa_recebida"]:
            return jsonify({
                "mensagem": (
                    "A recompensa desta missão "
                    "já foi recebida."
                ),
                "code": "MISSION_ALREADY_CLAIMED",
                "xp_ganho": 0,
                "xp_total": (
                    dados_missoes["aluno"]["xp_total"]
                ),
                "missao": missao_atual,
            }), 200

        data_missao = dados_missoes["data"]

        try:
            (
                supabase_admin
                .table("recompensas_missoes")
                .insert({
                    "aluno_id": aluno_id,
                    "missao_codigo": missao_codigo,
                    "data_missao": data_missao,
                    "xp_recebido": configuracao["xp"],
                })
                .execute()
            )

        except Exception as erro_insercao:
            texto_erro = str(
                erro_insercao
            ).lower()

            recompensa_duplicada = (
                "23505" in texto_erro
                or "duplicate key" in texto_erro
                or "unique constraint" in texto_erro
                or "recompensa_missao_unica"
                in texto_erro
            )

            if recompensa_duplicada:
                aluno_atualizado = (
                    buscar_aluno_para_missoes(
                        aluno_id
                    )
                )

                return jsonify({
                    "mensagem": (
                        "A recompensa desta missão "
                        "já foi recebida."
                    ),
                    "code": "MISSION_ALREADY_CLAIMED",
                    "xp_ganho": 0,
                    "xp_total": int(
                        aluno_atualizado.get(
                            "xp_total",
                            0,
                        )
                        if aluno_atualizado
                        else 0
                    ),
                }), 200

            raise

        aluno_atualizado = (
            buscar_aluno_para_missoes(
                aluno_id
            )
        )

        return jsonify({
            "mensagem": "Recompensa recebida!",
            "code": "MISSION_REWARD_CLAIMED",
            "xp_ganho": configuracao["xp"],
            "xp_total": int(
                aluno_atualizado.get(
                    "xp_total",
                    0,
                )
                if aluno_atualizado
                else 0
            ),
            "missao_codigo": missao_codigo,
            "data_missao": data_missao,
        }), 201

    except Exception:
        current_app.logger.exception(
            "Erro ao resgatar recompensa de missão."
        )

        return jsonify({
            "erro": (
                "Não foi possível resgatar "
                "a recompensa."
            ),
            "code": "MISSION_REWARD_ERROR",
        }), 500

@alunos_bp.route('/perfil/<int:aluno_id>', methods=['GET'])
def obter_perfil_gameplay(aluno_id):
    try:
        # 1. Busca dados do aluno
        aluno_res = supabase.table('alunos') \
            .select('id, nome, ano_escolar, email, modo_aprendizagem, hiperfoco, xp_total, professor_id') \
            .eq('id', aluno_id) \
            .execute()
            
        if not aluno_res.data:
            return jsonify({"erro": "Registro de aluno inexistente."}), 404

        aluno = aluno_res.data[0]

        # 2. Busca o nome do professor com tratamento seguro caso professor_id seja NULL
        nome_professor = "Não atribuído"
        professor_id = aluno.get("professor_id")

        if professor_id:
            prof_res = supabase.table('professores') \
                .select('nome') \
                .eq('id', professor_id) \
                .execute()
            
            if prof_res.data and len(prof_res.data) > 0:
                nome_professor = prof_res.data[0].get("nome", "Não atribuído")

        # 3. Consulta avaliação inicial (se existir)
        avaliacao_res = supabase.table('avaliacao_inicial') \
            .select('nivel_comunicacao, forma_comunicacao, suporte_audio, resultado_modo') \
            .eq('aluno_id', aluno_id) \
            .order('id', desc=True) \
            .limit(1) \
            .execute()

        # 4. Consulta histórico de desempenho
        desempenho_res = supabase.table('historico_desempenho') \
            .select('id', count='exact') \
            .eq('aluno_id', aluno_id) \
            .eq('concluido', True) \
            .execute()

        total_concluidas = desempenho_res.count if desempenho_res.count is not None else 0
        avaliacao_dados = avaliacao_res.data[0] if avaliacao_res.data else {}

        payload = {
            "id": aluno.get("id"),
            "nome": aluno.get("nome"),
            "email": aluno.get("email"),
            "ano_escolar": aluno.get("ano_escolar"),
            "modo_aprendizagem": aluno.get("modo_aprendizagem"),
            "hiperfoco": aluno.get("hiperfoco"),
            "xp_total": aluno.get("xp_total") or 0,
            "professor": nome_professor,
            "atividades_concluidas": total_concluidas,
            "avaliacao": {
                "nivel_comunicacao": avaliacao_dados.get("nivel_comunicacao"),
                "forma_comunicacao": avaliacao_dados.get("forma_comunicacao"),
                "suporte_audio": avaliacao_dados.get("suporte_audio"),
                "resultado_modo": avaliacao_dados.get("resultado_modo")
            }
        }
            
        return jsonify(payload), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao resgatar perfil: {str(e)}"}), 500


@alunos_bp.route('/desempenho', methods=['POST'])
def salvar_desempenho():
    try:
        dados = request.get_json(silent=True)
        # ... (validações existentes) ...

        payload_insercao = {
            'aluno_id': int(dados.get('aluno_id')),
            'atividade_id': int(dados.get('atividade_id')),
            'modo_utilizado': str(dados.get('modo_utilizado')).strip(),
            'quantidade_erros': int(dados.get('quantidade_erros')),
            'tempo_segundos': int(dados.get('tempo_segundos')),
            'concluido': bool(dados.get('concluido'))
        }

        # 1. Salva o histórico de telemetria
        busca = supabase.table('historico_desempenho').insert(payload_insercao).execute()

        # 2. Calcula e incrementa XP no perfil do aluno se concluído com sucesso
        if dados.get('concluido'):
            xp_ganho = max(10, 50 - (int(dados.get('quantidade_erros')) * 5))
            
            # Busca XP atual do aluno
            aluno = supabase.table('alunos').select('xp_total').eq('id', dados.get('aluno_id')).execute()
            xp_atual = aluno.data[0].get('xp_total', 0) if aluno.data else 0
            
            # Atualiza total
            supabase.table('alunos').update({'xp_total': xp_atual + xp_ganho}).eq('id', dados.get('aluno_id')).execute()

        return jsonify({"mensagem": "Telemetria e progresso atualizados com sucesso!"}), 201

    except Exception as e:
        return jsonify({"erro": f"Erro de persistência: {str(e)}"}), 500