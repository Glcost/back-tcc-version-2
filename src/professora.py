import re
import secrets
import hashlib
import hmac
import html
import os
from datetime import datetime, timedelta

import resend
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

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return jsonify({
                "erro": "Informe um e-mail válido.",
                "code": "INVALID_EMAIL",
            }), 400

        if (
            len(senha) < 8
            or not re.search(r"[A-Z]", senha)
            or not re.search(r"[a-z]", senha)
            or not re.search(r"\d", senha)
        ):
            return jsonify({
                "erro": (
                    "A senha deve ter pelo menos 8 caracteres, "
                    "uma letra maiúscula, uma minúscula e um número."
                ),
                "code": "WEAK_PASSWORD",
            }), 400
        
        
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
            'cpf': cpf_texto,
            'email_verificado_em': None,
        }).execute()

        if not req.data:
            return jsonify({'erro': 'Falha ao registrar professor no banco de dados.'}), 500
        
        professor_criado = req.data[0]
        email_enviado = True

        try:
            _create_and_send_email_verification(professor_criado)
        except Exception as error:
            email_enviado = False
            print(
                "Falha no envio da verificação de e-mail: "
                f"{type(error).__name__}"
            )

        return jsonify({
            'mensagem': (
                'Cadastro realizado. Digite o código enviado ao seu e-mail.'
                if email_enviado
                else 'Cadastro realizado, mas o código não pôde ser enviado. Solicite o reenvio.'
            ),
            'email_verificado': False,
            'email_enviado': email_enviado,
            'professor': {
                'id': professor_criado['id'],
                'nome': professor_criado['nome'],
                'email': professor_criado['email'],
                'cpf': professor_criado['cpf']
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

    if not professor.get("email_verificado_em"):
        return jsonify({
            "erro": "Confirme seu e-mail antes de entrar.",
            "code": "EMAIL_NOT_VERIFIED",
        }), 403

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



@professores_bp.route(
    "/perfil/<int:professor_id>",
    methods=["GET"],
)
@token_obrigatorio
def obter_perfil_professor(professor_id):
    if not verificar_professor(
        professor_id,
        request.professor_id,
    ):
        return jsonify({
            "erro": "Acesso não autorizado a este perfil.",
            "code": "FORBIDDEN",
        }), 403

    try:
        resultado = (
            supabase
            .table("professores")
            .select(
                "id, nome, email, cpf, criado_em"
            )
            .eq("id", professor_id)
            .limit(1)
            .execute()
        )

        if not resultado.data:
            return jsonify({
                "erro": "Professor não encontrado.",
                "code": "TEACHER_NOT_FOUND",
            }), 404

        professor = resultado.data[0]

        return jsonify({
            "professor": {
                "id": professor.get("id"),
                "nome": professor.get("nome"),
                "email": professor.get("email"),
                "cpf": str(
                    professor.get("cpf") or ""
                ),
                "criado_em": professor.get(
                    "criado_em"
                ),
            },
        }), 200

    except Exception as error:
        return jsonify({
            "erro": (
                "Erro ao consultar o perfil: "
                f"{str(error)}"
            ),
            "code": "TEACHER_PROFILE_ERROR",
        }), 500


@professores_bp.route(
    "/perfil/<int:professor_id>",
    methods=["PUT"],
)
@token_obrigatorio
def atualizar_perfil_professor(professor_id):
    if not verificar_professor(
        professor_id,
        request.professor_id,
    ):
        return jsonify({
            "erro": "Acesso não autorizado a este perfil.",
            "code": "FORBIDDEN",
        }), 403

    try:
        dados = request.get_json(silent=True) or {}

        if not dados:
            return jsonify({
                "erro": "Nenhum dado foi enviado.",
                "code": "EMPTY_REQUEST",
            }), 400

        campos_permitidos = {
            "nome",
            "email",
            "cpf",
        }

        campos_desconhecidos = (
            set(dados.keys()) -
            campos_permitidos
        )

        if campos_desconhecidos:
            return jsonify({
                "erro": (
                    "Foram enviados campos que não "
                    "podem ser alterados."
                ),
                "code": "INVALID_FIELDS",
                "campos": sorted(
                    campos_desconhecidos
                ),
            }), 400

        atualizacao = {}

        if "nome" in dados:
            nome = str(
                dados.get("nome") or ""
            ).strip()

            if len(nome) < 3:
                return jsonify({
                    "erro": (
                        "O nome deve possuir pelo "
                        "menos 3 caracteres."
                    ),
                    "code": "INVALID_NAME",
                }), 400

            if len(nome) > 150:
                return jsonify({
                    "erro": (
                        "O nome deve possuir no "
                        "máximo 150 caracteres."
                    ),
                    "code": "INVALID_NAME",
                }), 400

            atualizacao["nome"] = nome

        if "email" in dados:
            email = str(
                dados.get("email") or ""
            ).strip().lower()

            formato_email = (
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
            )

            if not re.match(
                formato_email,
                email,
            ):
                return jsonify({
                    "erro": (
                        "Informe um endereço de "
                        "e-mail válido."
                    ),
                    "code": "INVALID_EMAIL",
                }), 400

            email_existente = (
                supabase
                .table("professores")
                .select("id")
                .eq("email", email)
                .neq("id", professor_id)
                .limit(1)
                .execute()
            )

            if email_existente.data:
                return jsonify({
                    "erro": (
                        "Este e-mail já está sendo "
                        "utilizado."
                    ),
                    "code": "EMAIL_ALREADY_EXISTS",
                }), 409

            atualizacao["email"] = email

        if "cpf" in dados:
            cpf_formatado = str(
                dados.get("cpf") or ""
            ).strip()

            cpf = re.sub(
                r"\D",
                "",
                cpf_formatado,
            )

            if len(cpf) != 11:
                return jsonify({
                    "erro": (
                        "O CPF deve possuir "
                        "11 números."
                    ),
                    "code": "INVALID_CPF",
                }), 400

            if not cpf_validate.validate(cpf):
                return jsonify({
                    "erro": "O CPF informado é inválido.",
                    "code": "INVALID_CPF",
                }), 400

            cpf_existente = (
                supabase
                .table("professores")
                .select("id")
                .eq("cpf", cpf)
                .neq("id", professor_id)
                .limit(1)
                .execute()
            )

            if cpf_existente.data:
                return jsonify({
                    "erro": (
                        "Este CPF já está sendo "
                        "utilizado."
                    ),
                    "code": "CPF_ALREADY_EXISTS",
                }), 409

            atualizacao["cpf"] = cpf

        if not atualizacao:
            return jsonify({
                "erro": (
                    "Nenhum campo válido foi "
                    "informado para atualização."
                ),
                "code": "NO_VALID_FIELDS",
            }), 400

        resultado = (
            supabase
            .table("professores")
            .update(atualizacao)
            .eq("id", professor_id)
            .execute()
        )

        if not resultado.data:
            return jsonify({
                "erro": (
                    "Não foi possível atualizar "
                    "o perfil."
                ),
                "code": "PROFILE_UPDATE_FAILED",
            }), 500

        professor = resultado.data[0]

        return jsonify({
            "mensagem": (
                "Perfil atualizado com sucesso."
            ),
            "professor": {
                "id": professor.get("id"),
                "nome": professor.get("nome"),
                "email": professor.get("email"),
                "cpf": str(
                    professor.get("cpf") or ""
                ),
                "criado_em": professor.get(
                    "criado_em"
                ),
            },
        }), 200

    except Exception as error:
        return jsonify({
            "erro": (
                "Erro ao atualizar o perfil: "
                f"{str(error)}"
            ),
            "code": "TEACHER_PROFILE_UPDATE_ERROR",
        }), 500






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


# ==========================================================
# RECUPERAÇÃO DE SENHA DO PROFESSOR
# ==========================================================
RECOVERY_CODE_MINUTES = 10
RECOVERY_MAX_ATTEMPTS = 5
RECOVERY_REQUEST_INTERVAL_SECONDS = 60
GENERIC_RECOVERY_MESSAGE = (
    "Se o e-mail estiver cadastrado, enviaremos um código de recuperação."
)


def _recovery_configuration():
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "").strip()
    pepper = os.getenv("PASSWORD_RESET_PEPPER", "").strip()

    if not api_key or not from_email or not pepper:
        raise RuntimeError(
            "As variáveis de recuperação de senha não foram configuradas."
        )

    return api_key, from_email, pepper


def _normalize_recovery_email(value):
    email = str(value or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return None
    return email


def _hash_recovery_code(professor_id, code, pepper):
    message = f"{int(professor_id)}:{str(code)}".encode("utf-8")
    return hmac.new(
        pepper.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _find_professor_by_email(email):
    result = (
        supabase.table("professores")
        .select("id, nome, email, email_verificado_em")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _latest_active_recovery(professor_id):
    result = (
        supabase.table("recuperacoes_senha_professor")
        .select("id, professor_id, codigo_hash, expira_em, tentativas, utilizado_em, criado_em")
        .eq("professor_id", professor_id)
        .is_("utilizado_em", "null")
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _parse_database_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _validate_recovery_code(professor, code, count_attempt=True):
    recovery = _latest_active_recovery(professor["id"])
    if not recovery:
        return None, "Código inválido ou expirado."

    expires_at = _parse_database_datetime(recovery.get("expira_em"))
    attempts = int(recovery.get("tentativas") or 0)

    if not expires_at or datetime.utcnow() >= expires_at:
        return None, "Código inválido ou expirado."

    if attempts >= RECOVERY_MAX_ATTEMPTS:
        return None, "O limite de tentativas foi atingido. Solicite outro código."

    _, _, pepper = _recovery_configuration()
    received_hash = _hash_recovery_code(professor["id"], code, pepper)
    valid = hmac.compare_digest(received_hash, recovery["codigo_hash"])

    if not valid and count_attempt:
        supabase.table("recuperacoes_senha_professor").update({
            "tentativas": attempts + 1,
        }).eq("id", recovery["id"]).execute()

    if not valid:
        return None, "Código inválido ou expirado."

    return recovery, None


def _send_recovery_email(professor, code):
    api_key, from_email, _ = _recovery_configuration()
    resend.api_key = api_key
    safe_name = html.escape(str(professor.get("nome") or "Professor"))
    safe_code = html.escape(str(code))

    resend.Emails.send({
        "from": from_email,
        "to": [professor["email"]],
        "subject": "Código para redefinir sua senha no ROAR",
        "html": f"""
            <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#172b3f">
                <h1 style="color:#1f6ce3">Recuperação de senha</h1>
                <p>Olá, {safe_name}.</p>
                <p>Use o código abaixo para redefinir sua senha no ROAR:</p>
                <p style="font-size:32px;font-weight:700;letter-spacing:8px">{safe_code}</p>
                <p>Ele expira em {RECOVERY_CODE_MINUTES} minutos.</p>
                <p>Se você não solicitou esta alteração, ignore esta mensagem.</p>
            </div>
        """,
    })


@professores_bp.route("/senha/solicitar-recuperacao", methods=["POST"])
def solicitar_recuperacao_senha():
    data = request.get_json(silent=True) or {}
    email = _normalize_recovery_email(data.get("email"))

    if not email:
        return jsonify({"erro": "Informe um e-mail válido.", "code": "INVALID_EMAIL"}), 400

    try:
        professor = _find_professor_by_email(email)
        if not professor:
            return jsonify({"mensagem": GENERIC_RECOVERY_MESSAGE}), 200

        latest = _latest_active_recovery(professor["id"])
        if latest:
            created_at = _parse_database_datetime(latest.get("criado_em"))
            if created_at and (datetime.utcnow() - created_at).total_seconds() < RECOVERY_REQUEST_INTERVAL_SECONDS:
                return jsonify({"mensagem": GENERIC_RECOVERY_MESSAGE}), 200

        now = datetime.utcnow()
        supabase.table("recuperacoes_senha_professor").update({
            "utilizado_em": now.isoformat(),
        }).eq("professor_id", professor["id"]).is_("utilizado_em", "null").execute()

        code = f"{secrets.randbelow(1000000):06d}"
        _, _, pepper = _recovery_configuration()
        insertion = supabase.table("recuperacoes_senha_professor").insert({
            "professor_id": professor["id"],
            "codigo_hash": _hash_recovery_code(professor["id"], code, pepper),
            "expira_em": (now + timedelta(minutes=RECOVERY_CODE_MINUTES)).isoformat(),
        }).execute()

        try:
            _send_recovery_email(professor, code)
        except Exception:
            if insertion.data:
                supabase.table("recuperacoes_senha_professor").delete().eq("id", insertion.data[0]["id"]).execute()
            raise

        return jsonify({"mensagem": GENERIC_RECOVERY_MESSAGE}), 200
    except Exception as error:
        print(f"Falha ao solicitar recuperação: {type(error).__name__}")
        return jsonify({"mensagem": GENERIC_RECOVERY_MESSAGE}), 200


@professores_bp.route("/senha/validar-codigo", methods=["POST"])
def validar_codigo_recuperacao():
    data = request.get_json(silent=True) or {}
    email = _normalize_recovery_email(data.get("email"))
    code = re.sub(r"\D", "", str(data.get("codigo") or ""))

    if not email or len(code) != 6:
        return jsonify({"erro": "Código inválido ou expirado.", "code": "INVALID_RECOVERY_CODE"}), 400

    try:
        professor = _find_professor_by_email(email)
        recovery, error = _validate_recovery_code(professor, code) if professor else (None, None)
        if not recovery:
            return jsonify({"erro": error or "Código inválido ou expirado.", "code": "INVALID_RECOVERY_CODE"}), 400
        return jsonify({"mensagem": "Código validado com sucesso."}), 200
    except Exception:
        return jsonify({"erro": "Não foi possível validar o código.", "code": "RECOVERY_VALIDATION_ERROR"}), 500


@professores_bp.route("/senha/redefinir", methods=["POST"])
def redefinir_senha_professor():
    data = request.get_json(silent=True) or {}
    email = _normalize_recovery_email(data.get("email"))
    code = re.sub(r"\D", "", str(data.get("codigo") or ""))
    password = str(data.get("nova_senha") or "")
    confirmation = str(data.get("confirmacao_senha") or "")

    if not email or len(code) != 6:
        return jsonify({"erro": "Código inválido ou expirado.", "code": "INVALID_RECOVERY_CODE"}), 400
    if password != confirmation:
        return jsonify({"erro": "As senhas não coincidem.", "code": "PASSWORD_MISMATCH"}), 400
    if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
        return jsonify({"erro": "A senha deve ter pelo menos 8 caracteres, uma letra maiúscula, uma minúscula e um número.", "code": "WEAK_PASSWORD"}), 400

    try:
        professor = _find_professor_by_email(email)
        recovery, error = _validate_recovery_code(professor, code) if professor else (None, None)
        if not recovery:
            return jsonify({"erro": error or "Código inválido ou expirado.", "code": "INVALID_RECOVERY_CODE"}), 400

        supabase.table("professores").update({
            "senha": generate_password_hash(password),
        }).eq("id", professor["id"]).execute()

        supabase.table("recuperacoes_senha_professor").update({
            "utilizado_em": datetime.utcnow().isoformat(),
        }).eq("id", recovery["id"]).execute()

        return jsonify({"mensagem": "Senha redefinida com sucesso."}), 200
    except Exception:
        return jsonify({"erro": "Não foi possível redefinir a senha.", "code": "PASSWORD_RESET_ERROR"}), 500


# ==========================================================
# CONFIRMAÇÃO DE E-MAIL DO PROFESSOR
# ==========================================================
EMAIL_CODE_MINUTES = 10
EMAIL_CODE_MAX_ATTEMPTS = 5
EMAIL_CODE_RESEND_SECONDS = 60


def _hash_email_verification_code(professor_id, code, pepper):
    message = f"email:{int(professor_id)}:{str(code)}".encode("utf-8")
    return hmac.new(
        pepper.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _latest_email_verification(professor_id):
    result = (
        supabase.table("verificacoes_email_professor")
        .select("id, professor_id, codigo_hash, expira_em, tentativas, confirmado_em, criado_em")
        .eq("professor_id", professor_id)
        .is_("confirmado_em", "null")
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _send_email_verification(professor, code):
    api_key, from_email, _ = _recovery_configuration()
    resend.api_key = api_key
    safe_name = html.escape(str(professor.get("nome") or "Professor"))
    safe_code = html.escape(str(code))

    resend.Emails.send({
        "from": from_email,
        "to": [professor["email"]],
        "subject": "Confirme seu e-mail no ROAR",
        "html": f"""
            <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#172b3f">
                <h1 style="color:#1f6ce3">Confirmação de e-mail</h1>
                <p>Olá, {safe_name}.</p>
                <p>Use o código abaixo para confirmar seu cadastro no ROAR:</p>
                <p style="font-size:32px;font-weight:700;letter-spacing:8px">{safe_code}</p>
                <p>O código expira em {EMAIL_CODE_MINUTES} minutos.</p>
                <p>Se você não realizou este cadastro, ignore esta mensagem.</p>
            </div>
        """,
    })


def _create_and_send_email_verification(professor):
    now = datetime.utcnow()
    supabase.table("verificacoes_email_professor").update({
        "confirmado_em": now.isoformat(),
    }).eq("professor_id", professor["id"]).is_("confirmado_em", "null").execute()

    code = f"{secrets.randbelow(1000000):06d}"
    _, _, pepper = _recovery_configuration()
    insertion = supabase.table("verificacoes_email_professor").insert({
        "professor_id": professor["id"],
        "codigo_hash": _hash_email_verification_code(professor["id"], code, pepper),
        "expira_em": (now + timedelta(minutes=EMAIL_CODE_MINUTES)).isoformat(),
    }).execute()

    try:
        _send_email_verification(professor, code)
    except Exception:
        if insertion.data:
            supabase.table("verificacoes_email_professor").delete().eq(
                "id", insertion.data[0]["id"]
            ).execute()
        raise


def _validate_email_verification_code(professor, code):
    verification = _latest_email_verification(professor["id"])
    if not verification:
        return None, "Código inválido ou expirado."

    expires_at = _parse_database_datetime(verification.get("expira_em"))
    attempts = int(verification.get("tentativas") or 0)
    if not expires_at or datetime.utcnow() >= expires_at:
        return None, "Código inválido ou expirado."
    if attempts >= EMAIL_CODE_MAX_ATTEMPTS:
        return None, "O limite de tentativas foi atingido. Solicite outro código."

    _, _, pepper = _recovery_configuration()
    received_hash = _hash_email_verification_code(professor["id"], code, pepper)
    valid = hmac.compare_digest(received_hash, verification["codigo_hash"])

    if not valid:
        supabase.table("verificacoes_email_professor").update({
            "tentativas": attempts + 1,
        }).eq("id", verification["id"]).execute()
        return None, "Código inválido ou expirado."

    return verification, None


@professores_bp.route("/email/confirmar", methods=["POST"])
def confirmar_email_professor():
    data = request.get_json(silent=True) or {}
    email = _normalize_recovery_email(data.get("email"))
    code = re.sub(r"\D", "", str(data.get("codigo") or ""))

    if not email or len(code) != 6:
        return jsonify({"erro": "Código inválido ou expirado.", "code": "INVALID_EMAIL_CODE"}), 400

    try:
        professor = _find_professor_by_email(email)
        if not professor:
            return jsonify({"erro": "Código inválido ou expirado.", "code": "INVALID_EMAIL_CODE"}), 400
        if professor.get("email_verificado_em"):
            return jsonify({"mensagem": "Este e-mail já foi confirmado."}), 200

        verification, error = _validate_email_verification_code(professor, code)
        if not verification:
            return jsonify({"erro": error, "code": "INVALID_EMAIL_CODE"}), 400

        now = datetime.utcnow().isoformat()
        supabase.table("professores").update({
            "email_verificado_em": now,
        }).eq("id", professor["id"]).execute()
        supabase.table("verificacoes_email_professor").update({
            "confirmado_em": now,
        }).eq("id", verification["id"]).execute()

        return jsonify({"mensagem": "E-mail confirmado com sucesso."}), 200
    except Exception:
        return jsonify({"erro": "Não foi possível confirmar o e-mail.", "code": "EMAIL_CONFIRMATION_ERROR"}), 500


@professores_bp.route("/email/reenviar-codigo", methods=["POST"])
def reenviar_codigo_email_professor():
    data = request.get_json(silent=True) or {}
    email = _normalize_recovery_email(data.get("email"))
    generic_message = "Se o cadastro estiver pendente, enviaremos um novo código."

    if not email:
        return jsonify({"erro": "Informe um e-mail válido.", "code": "INVALID_EMAIL"}), 400

    try:
        professor = _find_professor_by_email(email)
        if not professor or professor.get("email_verificado_em"):
            return jsonify({"mensagem": generic_message}), 200

        latest = _latest_email_verification(professor["id"])
        if latest:
            created_at = _parse_database_datetime(latest.get("criado_em"))
            if created_at and (datetime.utcnow() - created_at).total_seconds() < EMAIL_CODE_RESEND_SECONDS:
                return jsonify({"mensagem": generic_message}), 200

        _create_and_send_email_verification(professor)
        return jsonify({"mensagem": generic_message}), 200
    except Exception as error:
        print(f"Falha ao reenviar confirmação: {type(error).__name__}")
        return jsonify({"mensagem": generic_message}), 200
