from flask import Blueprint, request, jsonify
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase

alunos_bp = Blueprint('alunos', __name__)

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

        busca = supabase.table('alunos').select('*').eq('pin_acesso', pin_digitado).eq('email', email_limpo).execute()

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

        aluno_res = supabase.table('alunos').select('*').eq('id', aluno_id).single().execute()
        if not aluno_res.data:
            return jsonify({"erro": "Estudante não encontrado.", "code": "NOT_FOUND"}), 404

        aluno = aluno_res.data
        return jsonify({
            "id": aluno["id"],
            "name": aluno["nome"],
            "email": aluno["email"],
            "schoolYear": aluno.get("ano_escolar"),
            "supportLevel": aluno.get("modo_aprendizagem"),
            "xpTotal": aluno.get("xp_total", 0)
        }), 200

    except Exception as e:
        return jsonify({"erro": f"Falha ao carregar perfil atual: {str(e)}"}), 500





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