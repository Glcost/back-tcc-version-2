from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash , check_password_hash
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase

professores_bp = Blueprint('professores', __name__)



@professores_bp.route('/cadastro', methods=['POST'])
def cadastro_professor():
 try:
        dados = request.get_json(silent=True) or {}
        
        # 1. Validação de campos obrigatórios (Retorna HTTP 400)
        if not dados or 'nome' not in dados or 'email' not in dados or 'senha' not in dados:
            return jsonify({'erro': 'Precisa preencher todos os campos: nome, email e senha.'}), 400
        
        email = str(dados.get('email')).strip().lower()
        nome = str(dados.get('nome')).strip()
        senha = str(dados.get('senha')).strip()

        if not email or not nome or not senha:
            return jsonify({'erro': 'Os campos não podem estar em branco.'}), 400

        # 2. Verificação de e-mail duplicado no Supabase
        busca = supabase.table('professores').select('*').eq('email', email).execute()
        
        if len(busca.data) > 0:
            return jsonify({'erro': 'E-mail já cadastrado. Por favor, use outro e-mail ou faça login.'}), 409
        
        # 3. Hashing da senha e inserção
        senha_hashed = generate_password_hash(senha)
        
        req = supabase.table('professores').insert({
            'nome': nome,
            'email': email,
            'senha': senha_hashed
        }).execute()

        if not req.data:
            return jsonify({'erro': 'Falha ao registrar professor no banco de dados.'}), 500
        
        # 4. Retorno explícito de sucesso (HTTP 201)
        return jsonify({
            'mensagem': 'Professor cadastrado com sucesso!',
            'professor': {
                'id': req.data[0]['id'],
                'nome': req.data[0]['nome'],
                'email': req.data[0]['email']
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

@professores_bp.route('/professores/cadastrar-aluno', methods=['POST'])
@token_obrigatorio
def cadastrar_e_avaliar_aluno():
    try:
        dados = request.get_json(silent=True)
        
        # Validação inicial dos campos obrigatórios do aluno e do questionário
        campos_obrigatorios = ['professor_id', 'nome', 'email', 'ano_escolar', 'pergunta_a', 'pergunta_b']
        if not dados or not all(campo in dados for campo in campos_obrigatorios):
            return jsonify({"erro": "Dados insuficientes para cadastro e avaliação."}), 400

        pergunta_a = dados.get('pergunta_a')  # Espera: 'A1', 'A2' ou 'A3'
        pergunta_b = dados.get('pergunta_b')  # Espera: 'B1', 'B2' ou 'B3'

        # Aplicação rigorosa da Matriz de Decisão do Escopo
        if pergunta_a == 'A1' or pergunta_b == 'B1':
            nivel_calculado = 1
            modo_aprendizagem = 'Visual_Guiado'
            
        elif (pergunta_a == 'A2' and pergunta_b == 'B2') or \
             (pergunta_a == 'A2' and pergunta_b == 'B3') or \
             (pergunta_a == 'A3' and pergunta_b == 'B2'):
            nivel_calculado = 2
            modo_aprendizagem = 'Interativo_Visual'
            
        elif pergunta_a == 'A3' and pergunta_b == 'B3':
            nivel_calculado = 3
            modo_aprendizagem = 'Verbal'
            
        else:
            return jsonify({"erro": "Combinação de respostas inválida para a matriz de decisão."}), 400

        # 1. Insere o Aluno com o modo já classificado pelo algoritmo
        aluno_payload = {
            "professor_id": dados.get('professor_id'),
            "nome": dados.get('nome'),
            "email": dados.get('email'),
            "ano_escolar": dados.get('ano_escolar'),
            "modo_aprendizagem": modo_aprendizagem,
            "hiperfoco": dados.get('hiperfoco', None),
            "pin_acesso": dados.get('pin_acesso', '1234')
        }
        
        req_aluno = supabase.table('alunos').insert(aluno_payload).execute()
        if not req_aluno.data:
            return jsonify({"erro": "Erro ao registrar dados cadastrais do aluno."}), 500
            
        aluno_id = req_aluno.data[0]['id']

        # 2. Registra o histórico da avaliação inicial vinculada ao ID do aluno gerado
        avaliacao_payload = {
            "aluno_id": aluno_id,
            "nivel_comunicacao": pergunta_a, 
            "forma_comunicacao": pergunta_b,
            "suporte_audio": dados.get('suporte_audio', False),
            "resultado_modo": modo_aprendizagem
            # O nível calculado (1, 2 ou 3) pode ser inferido pelo modo ou adicionado como coluna extra se achar necessário
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
        return jsonify({"erro": f"Erro analítico no servidor do TCC: {str(e)}"}), 500
    

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