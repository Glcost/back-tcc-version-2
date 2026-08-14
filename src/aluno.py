from flask import Blueprint, request, jsonify
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase

alunos_bp = Blueprint('alunos', __name__)

@alunos_bp.route('/login', methods=['POST'])
def login_aluno():
    try: 
        dados = request.get_json(silent=True)

        if not dados or 'pin_acesso' not in dados or 'email' not in dados:
            return jsonify({"erro": "Os campos 'pin_acesso' e 'email' são obrigatórios."}), 400

        pin_digitado = str(dados.get('pin_acesso')).strip()
        email = str(dados.get('email')).strip().lower()

        busca = supabase.table('alunos').select('*').eq('pin_acesso', pin_digitado).eq('email', email).execute()

        if len(busca.data) == 0:
            return jsonify({"erro": "PIN ou email inválido."}), 401
            
        return jsonify({"mensagem": "Login aceito!", "aluno": busca.data[0]}), 200

    except Exception as e:
        return jsonify({"erro": f"Erro no processamento do login: {str(e)}"}), 500


@alunos_bp.route('/perfil/<int:aluno_id>', methods=['GET'])
def obter_perfil_gameplay(aluno_id):
    try:
        # Busca customizada trazendo metadados fundamentais para a customização da UI/UX do jogo
        busca = supabase.table('alunos') \
            .select('id', 'nome', 'ano_escolar', 'modo_aprendizagem', 'hiperfoco') \
            .eq('id', aluno_id) \
            .execute()
            
        if len(busca.data) == 0:
            return jsonify({"erro": "Registro de aluno inexistente."}), 404
            
        return jsonify(busca.data[0]), 200
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao resgatar perfil do jogador: {str(e)}"}), 500


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