from flask import Blueprint, jsonify
from collections import Counter, defaultdict
from statistics import mean
from datetime import datetime

from auth import token_obrigatorio
from src.bd_config import supabase, supabase_admin

relatorios_bp = Blueprint('relatorios', __name__)

# Para o BI, preferimos o cliente admin (secret key) pois ele lê dados
# agregados de vários alunos/professores sem ficar limitado pelo RLS.
# Se a secret key não estiver configurada no .env, cai para o cliente padrão.
_db = supabase_admin if supabase_admin else supabase


def _media(valores, casas=2):
    """Média segura: retorna 0 se a lista estiver vazia."""
    valores = [v for v in valores if v is not None]
    return round(mean(valores), casas) if valores else 0


def _percentual(parte, total, casas=1):
    return round((parte / total) * 100, casas) if total else 0


# ==========================================================
# 1. VISÃO GERAL DA PLATAFORMA
# ==========================================================
@relatorios_bp.route('/visao-geral', methods=['GET'])
@token_obrigatorio
def visao_geral():
    try:
        alunos = _db.table('alunos').select('id, modo_aprendizagem, xp_total').execute().data or []
        professores = _db.table('professores').select('id').execute().data or []
        modulos = _db.table('modulos').select('id, ativo').execute().data or []
        historico = _db.table('historico_desempenho') \
            .select('quantidade_erros, tempo_segundos, concluido') \
            .execute().data or []

        total_alunos = len(alunos)
        total_professores = len(professores)
        modulos_ativos = len([m for m in modulos if m.get('ativo')])

        concluidos = [h for h in historico if h.get('concluido')]

        distribuicao_modo = Counter(a.get('modo_aprendizagem') or 'Não definido' for a in alunos)

        resposta = {
            "totais": {
                "alunos": total_alunos,
                "professores": total_professores,
                "modulos_ativos": modulos_ativos,
                "atividades_registradas": len(historico),
                "atividades_concluidas": len(concluidos)
            },
            "taxa_conclusao_geral_pct": _percentual(len(concluidos), len(historico)),
            "media_erros_por_atividade": _media([h.get('quantidade_erros') for h in historico]),
            "media_tempo_segundos": _media([h.get('tempo_segundos') for h in historico]),
            "media_xp_por_aluno": _media([a.get('xp_total') for a in alunos]),
            "distribuicao_modo_aprendizagem": dict(distribuicao_modo)
        }

        return jsonify(resposta), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao gerar visão geral: {str(e)}"}), 500


# ==========================================================
# 2. DASHBOARD DO PROFESSOR (todos os alunos dele)
# ==========================================================
@relatorios_bp.route('/professor/<int:professor_id>', methods=['GET'])
@token_obrigatorio
def relatorio_professor(professor_id):
    try:
        alunos = _db.table('alunos') \
            .select('id, nome, modo_aprendizagem, xp_total') \
            .eq('professor_id', professor_id) \
            .execute().data or []

        if not alunos:
            return jsonify({"erro": "Nenhum aluno encontrado para este professor."}), 404

        ids_alunos = [a['id'] for a in alunos]

        historico = _db.table('historico_desempenho') \
            .select('aluno_id, quantidade_erros, tempo_segundos, concluido') \
            .in_('aluno_id', ids_alunos) \
            .execute().data or []

        # Agrupa histórico por aluno
        por_aluno = defaultdict(list)
        for h in historico:
            por_aluno[h['aluno_id']].append(h)

        distribuicao_modo = Counter(a.get('modo_aprendizagem') or 'Não definido' for a in alunos)

        alunos_detalhado = []
        for a in alunos:
            registros = por_aluno.get(a['id'], [])
            concluidos = [r for r in registros if r.get('concluido')]
            alunos_detalhado.append({
                "aluno_id": a['id'],
                "nome": a['nome'],
                "modo_aprendizagem": a.get('modo_aprendizagem'),
                "xp_total": a.get('xp_total') or 0,
                "atividades_tentadas": len(registros),
                "atividades_concluidas": len(concluidos),
                "media_erros": _media([r.get('quantidade_erros') for r in registros]),
                "media_tempo_segundos": _media([r.get('tempo_segundos') for r in registros])
            })

        # Ranking por XP (maior para menor)
        ranking_xp = sorted(alunos_detalhado, key=lambda x: x['xp_total'], reverse=True)

        # Alunos que podem precisar de atenção: média de erros mais alta
        # (só considera quem já tentou ao menos uma atividade)
        com_tentativas = [a for a in alunos_detalhado if a['atividades_tentadas'] > 0]
        alerta_dificuldade = sorted(com_tentativas, key=lambda x: x['media_erros'], reverse=True)[:5]

        resposta = {
            "professor_id": professor_id,
            "total_alunos": len(alunos),
            "distribuicao_modo_aprendizagem": dict(distribuicao_modo),
            "ranking_xp": ranking_xp,
            "alunos_com_possivel_dificuldade": alerta_dificuldade,
            "alunos": alunos_detalhado
        }

        return jsonify(resposta), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao gerar relatório do professor: {str(e)}"}), 500


# ==========================================================
# 3. RELATÓRIO INDIVIDUAL DO ALUNO (evolução no tempo)
# ==========================================================
@relatorios_bp.route('/aluno/<int:aluno_id>', methods=['GET'])
@token_obrigatorio
def relatorio_aluno(aluno_id):
    try:
        aluno_req = _db.table('alunos') \
            .select('id, nome, modo_aprendizagem, xp_total, ano_escolar') \
            .eq('id', aluno_id) \
            .execute()

        if not aluno_req.data:
            return jsonify({"erro": "Aluno não encontrado."}), 404

        aluno = aluno_req.data[0]

        historico = _db.table('historico_desempenho') \
            .select('atividade_id, modo_utilizado, quantidade_erros, tempo_segundos, concluido, data_hora') \
            .eq('aluno_id', aluno_id) \
            .order('data_hora') \
            .execute().data or []

        concluidos = [h for h in historico if h.get('concluido')]

        # Evolução agrupada por dia (útil para gráfico de linha do tempo no front)
        evolucao_por_dia = defaultdict(lambda: {"tentativas": 0, "concluidas": 0, "erros": []})
        for h in historico:
            data_hora = h.get('data_hora')
            dia = data_hora[:10] if data_hora else "sem_data"
            evolucao_por_dia[dia]["tentativas"] += 1
            evolucao_por_dia[dia]["erros"].append(h.get('quantidade_erros'))
            if h.get('concluido'):
                evolucao_por_dia[dia]["concluidas"] += 1

        evolucao = [
            {
                "data": dia,
                "tentativas": v["tentativas"],
                "concluidas": v["concluidas"],
                "media_erros": _media(v["erros"])
            }
            for dia, v in sorted(evolucao_por_dia.items())
        ]

        resposta = {
            "aluno": {
                "id": aluno['id'],
                "nome": aluno['nome'],
                "ano_escolar": aluno.get('ano_escolar'),
                "modo_aprendizagem": aluno.get('modo_aprendizagem'),
                "xp_total": aluno.get('xp_total') or 0
            },
            "resumo": {
                "atividades_tentadas": len(historico),
                "atividades_concluidas": len(concluidos),
                "taxa_conclusao_pct": _percentual(len(concluidos), len(historico)),
                "media_erros": _media([h.get('quantidade_erros') for h in historico]),
                "media_tempo_segundos": _media([h.get('tempo_segundos') for h in historico])
            },
            "evolucao_diaria": evolucao,
            "historico_bruto": historico
        }

        return jsonify(resposta), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao gerar relatório do aluno: {str(e)}"}), 500


# ==========================================================
# 4. RELATÓRIO POR MÓDULO (visão do conteúdo pedagógico)
# ==========================================================
@relatorios_bp.route('/modulo/<int:modulo_id>', methods=['GET'])
@token_obrigatorio
def relatorio_modulo(modulo_id):
    try:
        atividades = _db.table('atividades') \
            .select('id, palavra_chave, ordem_sequencia') \
            .eq('modulo_id', modulo_id) \
            .order('ordem_sequencia') \
            .execute().data or []

        if not atividades:
            return jsonify({"erro": "Nenhuma atividade encontrada para este módulo."}), 404

        ids_atividades = [a['id'] for a in atividades]

        historico = _db.table('historico_desempenho') \
            .select('atividade_id, quantidade_erros, tempo_segundos, concluido') \
            .in_('atividade_id', ids_atividades) \
            .execute().data or []

        por_atividade = defaultdict(list)
        for h in historico:
            por_atividade[h['atividade_id']].append(h)

        detalhe_atividades = []
        for a in atividades:
            registros = por_atividade.get(a['id'], [])
            concluidos = [r for r in registros if r.get('concluido')]
            detalhe_atividades.append({
                "atividade_id": a['id'],
                "palavra_chave": a['palavra_chave'],
                "ordem": a['ordem_sequencia'],
                "vezes_jogada": len(registros),
                "vezes_concluida": len(concluidos),
                "taxa_conclusao_pct": _percentual(len(concluidos), len(registros)),
                "media_erros": _media([r.get('quantidade_erros') for r in registros]),
                "media_tempo_segundos": _media([r.get('tempo_segundos') for r in registros])
            })

        # Atividade com maior dificuldade média (mais erros) - útil para o professor revisar conteúdo
        mais_dificeis = sorted(
            [d for d in detalhe_atividades if d['vezes_jogada'] > 0],
            key=lambda x: x['media_erros'],
            reverse=True
        )

        resposta = {
            "modulo_id": modulo_id,
            "total_atividades": len(atividades),
            "atividades": detalhe_atividades,
            "atividades_mais_dificeis": mais_dificeis[:5]
        }

        return jsonify(resposta), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao gerar relatório do módulo: {str(e)}"}), 500
