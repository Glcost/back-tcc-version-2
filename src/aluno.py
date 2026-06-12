from flask import Blueprint, request, jsonify
from src.bd_config import supabase

alunos_bp = Blueprint('alunos', __name__)

@alunos_bp.route('/api/aluno/login', methods=['POST'])
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


@alunos_bp.route('/api/aluno/perfil/<int:aluno_id>', methods=['GET'])
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


@alunos_bp.route('/api/desempenho', methods=['POST'])
def salvar_desempenho():
    try:
        dados = request.get_json(silent=True)
        
        if not dados:
            return jsonify({"erro": "Nenhum payload de telemetria detectado."}), 400
            
        # Validação estrita de chaves obrigatórias (Garante que restrições NOT NULL do Supabase não quebrem a rota)
        campos_obrigatorios = ['aluno_id', 'atividade_id', 'modo_utilizado', 'quantidade_erros', 'tempo_segundos', 'concluido']
        erros_validacao = [campo for campo in campos_obrigatorios if campo not in dados]
        
        if erros_validacao:
            return jsonify({"erro": f"Campos obrigatórios ausentes: {', '.join(erros_validacao)}"}), 400

        payload_insercao = {
            'aluno_id': int(dados.get('aluno_id')),
            'atividade_id': int(dados.get('atividade_id')),
            'modo_utilizado': str(dados.get('modo_utilizado')).strip(),
            'quantidade_erros': int(dados.get('quantidade_erros')),
            'tempo_segundos': int(dados.get('tempo_segundos')),
            'concluido': bool(dados.get('concluido'))
        }

        busca = supabase.table('historico_desempenho').insert(payload_insercao).execute()

        if not busca.data:
            return jsonify({"erro": "Falha operacional ao persistir dados de desempenho no banco."}), 500

        return jsonify({"mensagem": "Telemetria de desempenho registrada com sucesso!"}), 201

    except ValueError:
        return jsonify({"erro": "Tipagem incorreta dos parâmetros numéricos ou booleanos no JSON."}), 400
    except Exception as e:
        return jsonify({"erro": f"Erro de persistência de telemetria: {str(e)}"}), 500