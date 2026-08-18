from flask import Blueprint, request, jsonify
from src.bd_config import supabase

atividades_bp = Blueprint('atividades', __name__)


@atividades_bp.route('/modulos', methods=['GET'])
def listar_modulos():
    try:
        resposta = supabase.table('modulos').select('*').eq('ativo', True).order('id').execute()
        return jsonify(resposta.data), 200
    except Exception as e:
        return jsonify({'erro': 'Erro ao carregar módulos', 'detalhes': str(e)}), 500


@atividades_bp.route('/fase/<int:modulo_id>/aluno/<int:aluno_id>', methods=['GET'])
def obter_fases_aluno(modulo_id, aluno_id):
    try:
        # Recupera o modo de aprendizagem gerado para o aluno (ex: Visual_Guiado, Verbal, Interativo_Visual)
        aluno_res = supabase.table('alunos').select('modo_aprendizagem').eq('id', aluno_id).single().execute()
        if not aluno_res.data:
            return jsonify({'erro': 'Aluno não encontrado'}), 404

        modo_aluno = aluno_res.data.get('modo_aprendizagem')

        # Busca as atividades associadas ao módulo ordenadas pela sequência pedagógica
        atividades_res = supabase.table('atividades')\
            .select('id, palavra_chave, ordem_sequencia')\
            .eq('modulo_id', modulo_id)\
            .order('ordem_sequencia')\
            .execute()

        if not atividades_res.data:
            return jsonify({'modulo_id': modulo_id, 'aluno_id': aluno_id, 'fases': []}), 200

        fases = []
        for ativ in atividades_res.data:
            ativ_id = ativ['id']

            # Filtra a variação correspondente ao modo de aprendizagem do aluno
            variacao_res = supabase.table('variacoes_atividades')\
                .select('instrucao_lex, url_midia_padrao, tipo_interacao, resposta_correta')\
                .eq('atividade_id', ativ_id)\
                .eq('modo_alvo', modo_aluno)\
                .maybe_single()\
                .execute()

            variacao = variacao_res.data if variacao_res else {}

            # Prioriza foto real customizada se houver registro para este aluno e atividade
            custom_res = supabase.table('personalizacao_aluno')\
                .select('url_foto_real')\
                .eq('aluno_id', aluno_id)\
                .eq('atividade_id', ativ_id)\
                .maybe_single()\
                .execute()

            url_midia_final = (custom_res.data.get('url_foto_real') if custom_res and custom_res.data 
                              else variacao.get('url_midia_padrao'))

            fases.append({
                'atividade_id': ativ_id,
                'palavra_chave': ativ['palavra_chave'],
                'ordem_sequencia': ativ['ordem_sequencia'],
                'modo_aplicado': modo_aluno,
                'instrucao_lex': variacao.get('instrucao_lex'),
                'url_midia': url_midia_final,
                'tipo_interacao': variacao.get('tipo_interacao'),
                'resposta_correta': variacao.get('resposta_correta')
            })

        return jsonify({
            'modulo_id': modulo_id,
            'aluno_id': aluno_id,
            'modo_aprendizagem': modo_aluno,
            'fases': fases
        }), 200

    except Exception as e:
        return jsonify({'erro': 'Falha ao recuperar etapas do módulo', 'detalhes': str(e)}), 500


@atividades_bp.route('/progresso', methods=['POST'])
def salvar_progresso():
    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({'erro': 'Corpo da requisição inválido'}), 400

        aluno_id = dados.get('aluno_id')
        atividade_id = dados.get('atividade_id')
        modo_utilizado = dados.get('modo_utilizado')
        quantidade_erros = dados.get('quantidade_erros', 0)
        tempo_segundos = dados.get('tempo_segundos', 0)
        concluido = dados.get('concluido', True)
        xp_ganho = dados.get('xp_ganho', 0)

        if not aluno_id or not atividade_id or not modo_utilizado:
            return jsonify({'erro': 'Parâmetros aluno_id, atividade_id e modo_utilizado são obrigatórios'}), 400

        # Persistência do desempenho da tentativa na tabela historico_desempenho
        historico_payload = {
            'aluno_id': aluno_id,
            'atividade_id': atividade_id,
            'modo_utilizado': modo_utilizado,
            'quantidade_erros': quantidade_erros,
            'tempo_segundos': tempo_segundos,
            'concluido': concluido
        }
        supabase.table('historico_desempenho').insert(historico_payload).execute()

        # Atualização incremental do total de XP na tabela alunos
        if xp_ganho > 0:
            aluno_dados = supabase.table('alunos').select('xp_total').eq('id', aluno_id).single().execute()
            xp_atual = (aluno_dados.data.get('xp_total') or 0) if aluno_dados.data else 0
            supabase.table('alunos').update({'xp_total': xp_atual + xp_ganho}).eq('id', aluno_id).execute()

        return jsonify({'mensagem': 'Progresso e desempenho registrados com sucesso!'}), 200

    except Exception as e:
        return jsonify({'erro': 'Erro ao processar e registrar progresso', 'detalhes': str(e)}), 500