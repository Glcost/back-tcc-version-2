# src/atividades.py
from flask import Blueprint, request, jsonify
from auth import token_obrigatorio
from src.bd_config import supabase

atividades_bp = Blueprint('atividades', __name__)

@atividades_bp.route('/modulos', methods=['GET'])
@token_obrigatorio
def listar_modulos():
    try:
        res = supabase.table('modulos').select('id, nome, ativo').eq('ativo', True).execute()
        return jsonify(res.data or []), 200
    except Exception as e:
        return jsonify({"erro": f"Erro ao buscar módulos: {str(e)}"}), 500


@atividades_bp.route('/modulo/<int:modulo_id>/aluno/<int:aluno_id>', methods=['GET'])
@token_obrigatorio
def carregar_atividades_modulo(modulo_id, aluno_id):
    try:
        # 1. Busca dados do aluno para identificar o modo de aprendizagem
        aluno_res = supabase.table('alunos').select('modo_aprendizagem').eq('id', aluno_id).single().execute()
        if not aluno_res.data:
            return jsonify({"erro": "Aluno não encontrado.", "code": "NOT_FOUND"}), 404
        
        modo_aluno = aluno_res.data.get('modo_aprendizagem')

        # 2. Busca atividades pertencentes ao módulo ordenadas por sequência
        atv_res = supabase.table('atividades') \
            .select('id, palavra_chave, ordem_sequencia') \
            .eq('modulo_id', modulo_id) \
            .order('ordem_sequencia') \
            .execute()

        atividades = atv_res.data or []
        if not atividades:
            return jsonify([]), 200

        ids_atividades = [a['id'] for a in atividades]

        # 3. Busca variações correspondentes ao modo do aluno
        variacoes_res = supabase.table('variacoes_atividades') \
            .select('atividade_id, modo_alvo, instrucao_lex, url_midia_padrao, tipo_interacao, resposta_correta') \
            .in_('atividade_id', ids_atividades) \
            .eq('modo_alvo', modo_aluno) \
            .execute()

        # Indexa variações por atividade_id
        dict_variacoes = {v['atividade_id']: v for v in (variacoes_res.data or [])}

        # 4. Busca personalizações de imagem do aluno para estas atividades
        pers_res = supabase.table('personalizacao_aluno') \
            .select('atividade_id, url_foto_real') \
            .eq('aluno_id', aluno_id) \
            .in_('atividade_id', ids_atividades) \
            .execute()

        dict_fotos = {p['atividade_id']: p['url_foto_real'] for p in (pers_res.data or [])}

        # 5. Monta o payload final adaptado para o motor do frontend
        payload = []
        for atv in atividades:
            atv_id = atv['id']
            variacao = dict_variacoes.get(atv_id)

            if not variacao:
                continue

            # Prioriza a foto personalizada do aluno em relação à mídia padrão
            midia_final = dict_fotos.get(atv_id) or variacao.get('url_midia_padrao')

            payload.append({
                "atividade_id": atv_id,
                "palavra_chave": atv['palavra_chave'],
                "ordem_sequencia": atv['ordem_sequencia'],
                "modo_alvo": variacao['modo_alvo'],
                "instrucao_lex": variacao['instrucao_lex'],
                "tipo_interacao": variacao['tipo_interacao'],
                "resposta_correta": variacao['resposta_correta'],
                "url_midia": midia_final,
                "is_personalizada": atv_id in dict_fotos
            })

        return jsonify(payload), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao carregar atividades adaptadas: {str(e)}"}), 500


@atividades_bp.route('/progresso', methods=['POST'])
@token_obrigatorio
def registrar_progresso():
    try:
        dados = request.get_json(silent=True) or {}
        
        aluno_id = dados.get('aluno_id') or request.aluno_id
        atividade_id = dados.get('atividade_id')
        modo_utilizado = dados.get('modo_utilizado')
        quantidade_erros = dados.get('quantidade_erros', 0)
        tempo_segundos = dados.get('tempo_segundos', 0)
        concluido = dados.get('concluido', True)
        xp_ganho = dados.get('xp_ganho', 10)

        if not aluno_id or not atividade_id or not modo_utilizado:
            return jsonify({"erro": "Campos 'aluno_id', 'atividade_id' e 'modo_utilizado' são obrigatórios."}), 400

        # Grava registro em historico_desempenho
        historico_payload = {
            "aluno_id": aluno_id,
            "atividade_id": atividade_id,
            "modo_utilizado": modo_utilizado,
            "quantidade_erros": quantidade_erros,
            "tempo_segundos": tempo_segundos,
            "concluido": concluido
        }
        
        supabase.table('historico_desempenho').insert(historico_payload).execute()

        # Incrementa o XP total do aluno em caso de conclusão
        if concluido and xp_ganho > 0:
            aluno_atual = supabase.table('alunos').select('xp_total').eq('id', aluno_id).single().execute()
            xp_atual = (aluno_atual.data.get('xp_total') or 0) if aluno_atual.data else 0
            
            supabase.table('alunos').update({"xp_total": xp_atual + xp_ganho}).eq('id', aluno_id).execute()

        return jsonify({"mensagem": "Progresso registrado com sucesso!"}), 201

    except Exception as e:
        return jsonify({"erro": f"Erro ao salvar histórico de desempenho: {str(e)}"}), 500