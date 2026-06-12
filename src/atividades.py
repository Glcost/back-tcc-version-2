from flask import Blueprint, jsonify
from src.bd_config import supabase

atividades_bp = Blueprint('atividades', __name__)

@atividades_bp.route('/api/modulos', methods=['GET'])
def listar_modulos():
    try:
        busca = supabase.table('modulos').select('*').eq('ativo', True).execute()
        return jsonify(busca.data), 200
    except Exception as e:
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500

@atividades_bp.route('/api/fase/<int:modulo_id>/aluno/<int:aluno_id>', methods=['GET'])
def carregar_fase_jogo(modulo_id, aluno_id):
    try:
        # Busca o modo de aprendizagem específico do aluno
        aluno_req = supabase.table('alunos').select('modo_aprendizagem').eq('id', aluno_id).execute()
        
        if not aluno_req.data:
            return jsonify({"erro": "Aluno não encontrado."}), 404
            
        modo_aluno = aluno_req.data[0]['modo_aprendizagem']

        # Junção de dados: Busca a atividade e traz as variações e personalizações
        atividades_req = supabase.table('atividades') \
            .select('id, palavra_chave, ordem_sequencia, variacoes_atividades(*), personalizacao_aluno(*)') \
            .eq('modulo_id', modulo_id) \
            .order('ordem_sequencia') \
            .execute()

        # Evita processamento desnecessário se o módulo estiver vazio
        if not atividades_req.data:
            return jsonify({"erro": "Nenhuma atividade encontrada para este módulo."}), 404

        fases_filtradas = []
        for atv in atividades_req.data:
            # Filtra a variação de instrução que bate com o perfil do aluno
            variacao_correta = next((v for v in atv.get('variacoes_atividades', []) if v['modo_alvo'] == modo_aluno), None)
            
            # Busca a foto personalizada vinculada ao aluno atual, se existir
            foto_personalizada = next((p['url_foto_real'] for p in atv.get('personalizacao_aluno', []) if p['aluno_id'] == aluno_id), None)
            
            if variacao_correta:
                fases_filtradas.append({
                    "atividade_id": atv['id'],
                    "palavra_chave": atv['palavra_chave'],
                    "ordem": atv['ordem_sequencia'],
                    "instrucao_lex": variacao_correta['instrucao_lex'],
                    "tipo_interacao": variacao_correta['tipo_interacao'],
                    "resposta_correta": variacao_correta['resposta_correta'],
                    # Lógica de fallback: Prioriza a foto real; se nula, usa a mídia padrão
                    "midia": foto_personalizada if foto_personalizada else variacao_correta.get('url_midia_padrao')
                })

        return jsonify({"fases": fases_filtradas}), 200

    except Exception as e:
        return jsonify({"erro": f"Erro na montagem da fase: {str(e)}"}), 500