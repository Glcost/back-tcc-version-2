from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash , check_password_hash
from validate_docbr import CPF
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase

cpf_validate = CPF()

professores_bp = Blueprint('professores', __name__)


@professores_bp.route('/cadastro', methods=['POST'])
def cadastro_professor():
    try:
        dados = request.get_json(silent=True) or {}
        
        # 1. Validação de campos obrigatórios
        campos = ['nome', 'email', 'senha', 'cpf']
        if not all(k in dados and str(dados[k]).strip() for k in campos):
            return jsonify({'erro': 'Todos os campos são obrigatórios: nome, email, senha e CPF.'}), 400
        
        email = str(dados.get('email')).strip().lower()
        nome = str(dados.get('nome')).strip()
        senha = str(dados.get('senha')).strip()
        cpf_texto = str(dados.get('cpf')).strip()
        
        
        if not cpf_validate.validate(cpf_texto):
            return jsonify({'erro': 'CPF informado é inválido'})

        # 2. Verificação de e-mail duplicado
        busca = supabase.table('professores').select('id').eq('email', email).execute()
        if len(busca.data) > 0:
            return jsonify({'erro': 'E-mail já cadastrado.'}), 409
        
        # 3. Hashing da senha e inserção no Supabase
        senha_hashed = generate_password_hash(senha)
        
        req = supabase.table('professores').insert({
            'nome': nome,
            'email': email,
            'senha': senha_hashed,
            'cpf': cpf_texto
        }).execute()

        if not req.data:
            return jsonify({'erro': 'Falha ao registrar professor no banco de dados.'}), 500
        
        return jsonify({
            'mensagem': 'Professor cadastrado com sucesso!',
            'professor': {
                'id': req.data[0]['id'],
                'nome': req.data[0]['nome'],
                'email': req.data[0]['email'],
                'cpf': req.data[0]['cpf']
            }
        }), 201
        
    except Exception as e:
        return jsonify({"erro": f"Erro interno no servidor: {str(e)}"}), 500
        


@professores_bp.route('/login', methods=['POST'])
def login_professor():
    dados = request.get_json() or {}
    email = dados.get('email')
    senha = dados.get('senha')
    

    # Validação rápida de campos vazios
    if not email or not senha:
        return jsonify({"erro": "E-mail e senha são obrigatórios."}), 400

    # 1. Busca a professora pelo e-mail no Supabase
    busca = supabase.table('professores').select('*').eq('email', str(email).strip().lower()).execute()

    if not busca.data:
        return jsonify({"erro": "E-mail ou senha incorretos."}), 401

    professor = busca.data[0]
    senha_banco = professor.get('senha', '')

    # 2. Confere a senha (seja ela hash ou texto puro dos seus inserts de teste)
    senha_valida = check_password_hash(senha_banco, str(senha)) or (senha_banco == str(senha))
    
    if not senha_valida:
        return jsonify({"erro": "E-mail ou senha incorretos."}), 401

    # 3. Gera o token JWT e envia a resposta
    token = gerar_token({"id": professor['id'], "nome": professor['nome']})

    return jsonify({
        "mensagem": f"Bem-vinda de volta, {professor['nome']}!",
        "token": token,
        "professor": {
            "id": professor['id'],
            "nome": professor['nome'],
            "email": professor['email']
        }
    }), 200

#Lista os alunos do professor
@professores_bp.route('/aluno/professor/<int:professor_id>', methods=['GET'])
@token_obrigatorio
def lista_alunos(professor_id):
    try:
        busca = supabase.table('alunos').select("*").eq('professor_id', professor_id).execute()
        return jsonify(busca.data), 200

    except Exception as e:
        return jsonify({"erro": f"Erro interno no servidor: {str(e)}"}), 500

@professores_bp.route('/cadastrar-aluno', methods=['POST'])
@token_obrigatorio
def cadastrar_e_avaliar_aluno():
    try:
        dados = request.get_json(silent=True) or {}
        
        # Validação dos campos obrigatórios
        campos_obrigatorios = ['professor_id', 'nome', 'email','cpf_aluno' 'ano_escolar', 'pergunta_a', 'pergunta_b']
        if not all(campo in dados for campo in campos_obrigatorios):
            return jsonify({"erro": "Dados insuficientes para cadastro e avaliação."}), 400

        pergunta_a = dados.get('pergunta_a')
        pergunta_b = dados.get('pergunta_b')

        # Dicionário para conversão direta de nível em modo de aprendizagem
        modos_map = {
            1: 'Visual Guiado',
            2: 'Interativo Visual',
            3: 'Verbal'
        }

        # 1. Prioriza o nível ajustado manualmente pela professora no Step 3
        nivel_manual = dados.get('nivel')
        if nivel_manual and int(nivel_manual) in modos_map:
            nivel_calculado = int(nivel_manual)
            modo_aprendizagem = modos_map[nivel_calculado]
        else:
            # 2. Caso não venha alteração manual, aplica a Matriz de Decisão
            if pergunta_a == 'A1' or pergunta_b == 'B1':
                nivel_calculado = 1
                modo_aprendizagem = 'Visual Guiado'
            elif (pergunta_a == 'A2' and pergunta_b in ['B2', 'B3']) or (pergunta_a == 'A3' and pergunta_b == 'B2'):
                nivel_calculado = 2
                modo_aprendizagem = 'Interativo Visual'
            elif pergunta_a == 'A3' and pergunta_b == 'B3':
                nivel_calculado = 3
                modo_aprendizagem = 'Verbal'
            else:
                return jsonify({"erro": "Combinação de respostas inválida para a matriz de decisão."}), 400

        # Persistência na tabela 'alunos'
        aluno_payload = {
            "professor_id": dados.get('professor_id'),
            "nome": dados.get('nome'),
            "email": dados.get('email'),
            "ano_escolar": dados.get('ano_escolar'),
            "cpf_aluno": dados.get('cpf_aluno'),
            "modo_aprendizagem": modo_aprendizagem,
            "pin_acesso": dados.get('pin_acesso', '1234')
        }
        
        req_aluno = supabase.table('alunos').insert(aluno_payload).execute()
        if not req_aluno.data:
            return jsonify({"erro": "Erro ao registrar dados cadastrais do aluno."}), 500
            
        aluno_id = req_aluno.data[0]['id']

        # Persistência na tabela 'avaliacao_inicial'
        avaliacao_payload = {
            "aluno_id": aluno_id,
            "nivel_comunicacao": pergunta_a, 
            "forma_comunicacao": pergunta_b,
            "suporte_audio": dados.get('suporte_audio', False),
            "resultado_modo": modo_aprendizagem
        }
        
        req_avaliacao = supabase.table('avaliacao_inicial').insert(avaliacao_payload).execute()
        if not req_avaliacao.data:
            return jsonify({"erro": "Aluno cadastrado, mas falhou ao salvar o relatório da avaliação."}), 500

        return jsonify({
            "mensagem": "Aluno cadastrado e classificado com sucesso!",
            "aluno_id": aluno_id,
            "nivel_identificado": nivel_calculado,
            "modo_definido": modo_aprendizagem
        }), 201

    except Exception as e:
        return jsonify({"erro": f"Erro analítico no servidor: {str(e)}"}), 500
    

@professores_bp.route('/alunos/<int:id>', methods=['PUT'])
@token_obrigatorio
def editar_aluno(id):
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"erro": "Nenhum dado fornecido para atualização."}), 400

        # Criamos um mapa/dicionário vazio
        campos_para_atualizar = {}

        # Só adicionamos ao mapa se o campo veio na requisição
        if 'modo_aprendizagem' in dados:
            campos_para_atualizar['modo_aprendizagem'] = dados.get('modo_aprendizagem')
        if 'nome' in dados:
            campos_para_atualizar['nome'] = dados.get('nome')
        if 'ano_escolar' in dados:
            campos_para_atualizar['ano_escolar'] = dados.get('ano_escolar')

        # Se o usuário mandou um JSON mas sem nenhum dos campos válidos
        if not campos_para_atualizar:
            return jsonify({"erro": "Nenhum campo válido para atualização foi enviado."}), 400

        # Mandamos atualizar APENAS os campos que foram alterados
        busca = supabase.table('alunos').update(campos_para_atualizar).eq('id', id).execute()
        
        return jsonify({"mensagem": "Perfil do aluno atualizado!", "aluno": busca.data[0]}), 200

    except Exception as e:
        return jsonify({"erro": str(e)}), 500



@professores_bp.route('/alunos/<int:id>', methods=['DELETE'])
@token_obrigatorio
def apagar_alunos(id):
    try:

        busca = supabase.table('alunos').delete().eq('id', id).execute()

        return jsonify({"mensagem": f"Aluno removido com sucesso {busca.data}"}), 200
    
    except Exception as e:
        return jsonify({"erro": str(e)}), 500






@professores_bp.route('/desempenho/aluno/<int:aluno_id>', methods=['GET'])
@token_obrigatorio
def obter_desempenho_aluno(aluno_id):
    try:
        # 1. BUSCA NA TABELA CORRETA: historico_desempenho
        # .order('data_hora', desc=True) garante que os relatórios mais novos fiquem no topo da dashboard
        busca = supabase.table('historico_desempenho') \
            .select('*') \
            .eq('aluno_id', aluno_id) \
            .order('data_hora', desc=True) \
            .execute()

        # 2. RETORNO PARA O FRONT-END
        return jsonify(busca.data), 200

    except Exception as e:
        return jsonify({"erro": f"Erro interno no servidor: {str(e)}"}), 500






@professores_bp.route('/dashboard/estatisticas/<int:professor_id>', methods=['GET'])
@token_obrigatorio
def estatisticas_dashboard(professor_id):
    try:
        # 1. Busca total de atividades ativas cadastradas no sistema
        atividades_req = supabase.table('atividades').select('id', count='exact').execute()
        total_atividades = atividades_req.count if atividades_req.count is not None else len(atividades_req.data)

        # 2. Busca lista de IDs de alunos vinculados a esta professora
        alunos_req = supabase.table('alunos').select('id').eq('professor_id', professor_id).execute()
        alunos_ids = [a['id'] for a in alunos_req.data]

        if not alunos_ids:
            return jsonify({
                'total_atividades': total_atividades,
                'media_turma': 0
            }), 200

        # 3. Calcula a taxa global de conclusão/sucesso do historico_desempenho da turma
        desempenho_req = supabase.table('historico_desempenho').select('concluido').in_('aluno_id', alunos_ids).execute()
        
        total_jogos = len(desempenho_req.data)
        if total_jogos == 0:
            media_turma = 0
        else:
            concluidos = sum(1 for d in desempenho_req.data if d.get('concluido'))
            media_turma = round((concluidos / total_jogos) * 100)

        return jsonify({
            'total_atividades': total_atividades,
            'media_turma': media_turma
        }), 200

    except Exception as e:
        return jsonify({"erro": f"Erro ao calcular estatísticas: {str(e)}"}), 500

@professores_bp.route('/alunos/perfil/<int:aluno_id>', methods=['GET'])
@token_obrigatorio
def obter_perfil_aluno(aluno_id):
    try:
        busca = supabase.table('alunos').select('id', 'nome', 'modo_aprendizagem').eq('id', aluno_id).execute()
        if len(busca.data) == 0:
            return jsonify({"erro": "Aluno não encontrado"}), 404
        return jsonify(busca.data[0]), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500