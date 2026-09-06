import re
import secrets
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash , check_password_hash
from validate_docbr import CPF
from auth import token_obrigatorio, gerar_token 
from src.bd_config import supabase

cpf_validate = CPF()

professores_bp = Blueprint('professores', __name__)

def verificar_professor(professor_id_rota,professor_id_token,):
    if (
        professor_id_rota is None
        or professor_id_token is None
    ):
        return False

    try:
        return (
            int(professor_id_rota)
            == int(professor_id_token)
        )
    except (TypeError, ValueError):
        return False

def verificar_professor_aluno(aluno_id, professor_id_token):
    res = supabase.table('alunos').select('professor_id').eq('id', aluno_id).execute()
    if not res.data:
        return False
    return res.data[0].get('professor_id') == professor_id_token

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
        cpf_formatado = str(dados.get("cpf", "")).strip()
        cpf_texto = re.sub(r"\D","",cpf_formatado,)
        
        
        if not cpf_validate.validate(cpf_texto):
            return jsonify({
            "erro": "CPF informado é inválido",
            "code": "INVALID_CPF",
            }), 400

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
    senha_valida = check_password_hash(senha_banco, str(senha))
    
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
    
    if not verificar_professor(professor_id, request.professor_id):
        return jsonify({"erro": "Acesso não autorizado a este professor."}), 403
    try:
        busca = supabase.table('alunos').select("*").eq('professor_id', professor_id).execute()
        return jsonify(busca.data), 200

    except Exception as e:
        return jsonify({"erro": f"Erro interno no servidor: {str(e)}"}), 500


def gerar_pin_aluno():
    tentativas_maximas = 20

    for _ in range(tentativas_maximas):
        pin = f"{secrets.randbelow(10000):04d}"

        resultado = (
            supabase
            .table("alunos")
            .select("id")
            .eq("pin_acesso", pin)
            .limit(1)
            .execute()
        )

        if not resultado.data:
            return pin

    raise RuntimeError(
        "Não foi possível gerar um PIN único."
    )



@professores_bp.route("/cadastrar-aluno",methods=["POST"])
@token_obrigatorio
def cadastrar_e_avaliar_aluno():
    try:
        dados = request.get_json(silent=True) or {}

        professor_id = request.professor_id

        if not professor_id:
            return jsonify({
                "erro": (
                    "Acesso permitido apenas para professores."
                ),
                "code": "FORBIDDEN",
            }), 403

        campos_obrigatorios = [
            "nome",
            "email",
            "cpf_aluno",
            "ano_escolar",
            "pergunta_a",
            "pergunta_b",
        ]

        campos_ausentes = [
            campo
            for campo in campos_obrigatorios
            if not str(dados.get(campo, "")).strip()
        ]

        if campos_ausentes:
            return jsonify({
                "erro": (
                    "Dados insuficientes para cadastro "
                    "e avaliação."
                ),
                "code": "MISSING_FIELDS",
                "campos": campos_ausentes,
            }), 400

        nome = str(
            dados.get("nome", "")
        ).strip()

        email = str(
            dados.get("email", "")
        ).strip().lower()

        ano_escolar = str(
            dados.get("ano_escolar", "")
        ).strip()

        cpf_formatado = str(
            dados.get("cpf_aluno", "")
        ).strip()

        cpf_aluno = re.sub(
            r"\D",
            "",
            cpf_formatado,
        )

        if len(cpf_aluno) != 11:
            return jsonify({
                "erro": "O CPF deve possuir 11 dígitos.",
                "code": "INVALID_CPF_LENGTH",
            }), 400

        if not cpf_validate.validate(cpf_aluno):
            return jsonify({
                "erro": (
                    "O CPF informado para o aluno "
                    "é inválido."
                ),
                "code": "INVALID_CPF",
            }), 400

        pergunta_a = dados.get("pergunta_a")
        pergunta_b = dados.get("pergunta_b")

        respostas_a_validas = {
            "A1",
            "A2",
            "A3",
        }

        respostas_b_validas = {
            "B1",
            "B2",
            "B3",
        }

        if (
            pergunta_a not in respostas_a_validas
            or pergunta_b not in respostas_b_validas
        ):
            return jsonify({
                "erro": (
                    "As respostas da triagem são inválidas."
                ),
                "code": "INVALID_TRIAGE_ANSWERS",
            }), 400

        if pergunta_a == "A1" or pergunta_b == "B1":
            nivel_calculado = 1
            modo_aprendizagem = "Visual Guiado"

        elif (
            pergunta_a == "A3"
            and pergunta_b == "B3"
        ):
            nivel_calculado = 3
            modo_aprendizagem = "Verbal"

        else:
            nivel_calculado = 2
            modo_aprendizagem = "Interativo Visual"

        email_existente = (
            supabase
            .table("alunos")
            .select("id")
            .eq("email", email)
            .execute()
        )

        if email_existente.data:
            return jsonify({
                "erro": (
                    "Já existe um aluno cadastrado "
                    "com este e-mail."
                ),
                "code": "EMAIL_ALREADY_EXISTS",
            }), 409

        cpf_existente = (
            supabase
            .table("alunos")
            .select("id")
            .eq("cpf_aluno", cpf_aluno)
            .execute()
        )

        if cpf_existente.data:
            return jsonify({
                "erro": (
                    "Já existe um aluno cadastrado "
                    "com este CPF."
                ),
                "code": "CPF_ALREADY_EXISTS",
            }), 409

        pin_acesso = gerar_pin_aluno()

        aluno_payload = {
            "professor_id": professor_id,
            "nome": nome,
            "email": email,
            "ano_escolar": ano_escolar,
            "cpf_aluno": cpf_aluno,
            "modo_aprendizagem": modo_aprendizagem,
            "pin_acesso": pin_acesso,
        }

        aluno_response = (
            supabase
            .table("alunos")
            .insert(aluno_payload)
            .execute()
        )

        if not aluno_response.data:
            return jsonify({
                "erro": (
                    "Não foi possível cadastrar o aluno."
                ),
                "code": "STUDENT_CREATION_FAILED",
            }), 500

        aluno_id = aluno_response.data[0]["id"]

        avaliacao_payload = {
            "aluno_id": aluno_id,
            "nivel_comunicacao": pergunta_a,
            "forma_comunicacao": pergunta_b,
            "suporte_audio": bool(
                dados.get("suporte_audio", False)
            ),
            "resultado_modo": modo_aprendizagem,
        }

        avaliacao_response = (
            supabase
            .table("avaliacao_inicial")
            .insert(avaliacao_payload)
            .execute()
        )

        if not avaliacao_response.data:
            return jsonify({
                "erro": (
                    "O aluno foi cadastrado, mas não foi "
                    "possível salvar a avaliação inicial."
                ),
                "code": "ASSESSMENT_CREATION_FAILED",
            }), 500

        return jsonify({
            "mensagem": (
                "Aluno cadastrado e classificado "
                "com sucesso."
            ),
            "aluno_id": aluno_id,
            "pin": pin_acesso,
            "nivel_identificado": nivel_calculado,
            "modo_definido": modo_aprendizagem,
        }), 201

    except Exception as error:
        return jsonify({
            "erro": (
                "Erro analítico no servidor: "
                f"{str(error)}"
            ),
            "code": "STUDENT_CREATION_ERROR",
        }), 500
    

@professores_bp.route('/alunos/<int:id>', methods=['PUT'])
@token_obrigatorio
def editar_aluno(aluno_id):
    try:
        if not verificar_professor_aluno(
            aluno_id,
            request.professor_id,
        ):
            return jsonify({
                "erro": (
                    "Acesso não autorizado a este aluno."
                ),
                "code": "FORBIDDEN",
            }), 403

        dados = request.get_json(silent=True) or {}

        if not dados:
            return jsonify({
                "erro": (
                    "Nenhum dado foi fornecido "
                    "para atualização."
                ),
                "code": "EMPTY_REQUEST",
            }), 400

        modos_por_nivel = {
            1: "Visual Guiado",
            2: "Interativo Visual",
            3: "Verbal",
        }

        campos_para_atualizar = {}

        if "nome" in dados:
            nome = str(
                dados.get("nome", "")
            ).strip()

            if not nome:
                return jsonify({
                    "erro": (
                        "O nome do aluno não pode "
                        "ficar vazio."
                    ),
                    "code": "INVALID_NAME",
                }), 400

            campos_para_atualizar["nome"] = nome

        if "ano_escolar" in dados:
            ano_escolar = str(
                dados.get("ano_escolar", "")
            ).strip()

            if not ano_escolar:
                return jsonify({
                    "erro": (
                        "O ano escolar não pode "
                        "ficar vazio."
                    ),
                    "code": "INVALID_SCHOOL_YEAR",
                }), 400

            campos_para_atualizar[
                "ano_escolar"
            ] = ano_escolar

        if "nivel" in dados:
            try:
                nivel = int(dados.get("nivel"))
            except (TypeError, ValueError):
                return jsonify({
                    "erro": (
                        "O nível informado é inválido."
                    ),
                    "code": "INVALID_SUPPORT_LEVEL",
                }), 400

            if nivel not in modos_por_nivel:
                return jsonify({
                    "erro": (
                        "O nível deve ser 1, 2 ou 3."
                    ),
                    "code": "INVALID_SUPPORT_LEVEL",
                }), 400

            campos_para_atualizar[
                "modo_aprendizagem"
            ] = modos_por_nivel[nivel]

        if not campos_para_atualizar:
            return jsonify({
                "erro": (
                    "Nenhum campo válido foi enviado "
                    "para atualização."
                ),
                "code": "NO_VALID_FIELDS",
            }), 400

        atualizacao = (
            supabase
            .table("alunos")
            .update(campos_para_atualizar)
            .eq("id", aluno_id)
            .execute()
        )

        if not atualizacao.data:
            return jsonify({
                "erro": (
                    "Não foi possível atualizar o aluno."
                ),
                "code": "STUDENT_UPDATE_FAILED",
            }), 500

        aluno = atualizacao.data[0]

        return jsonify({
            "mensagem": (
                "Dados do aluno atualizados "
                "com sucesso."
            ),
            "aluno": {
                "id": aluno.get("id"),
                "nome": aluno.get("nome"),
                "ano_escolar": aluno.get(
                    "ano_escolar"
                ),
                "modo_aprendizagem": aluno.get(
                    "modo_aprendizagem"
                ),
            },
        }), 200

    except Exception as error:
        return jsonify({
            "erro": (
                "Erro ao atualizar o aluno: "
                f"{str(error)}"
            ),
            "code": "STUDENT_UPDATE_ERROR",
        }), 500



@professores_bp.route('/alunos/<int:id>', methods=['DELETE'])
@token_obrigatorio
def apagar_alunos(id):
    try:

        if not verificar_professor_aluno(id, request.professor_id):
            return jsonify({"erro": "Acesso não autorizado a este aluno."}), 403

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
    if not verificar_professor(professor_id, request.professor_id):
        return jsonify({"erro": "Acesso não autorizado a este professor."}), 403
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