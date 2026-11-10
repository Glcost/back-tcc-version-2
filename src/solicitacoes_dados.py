"""Verified, teacher-assisted requests. This workflow never deletes student data."""
from datetime import datetime, timezone
import os
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request

from auth import token_obrigatorio
from src.bd_config import supabase_admin

solicitacoes_bp = Blueprint('solicitacoes_dados', __name__)
FIELDS = ('id', 'ordem', 'aluno_id', 'professor_abertura_id', 'atendido_por_id',
          'tipo', 'descricao', 'solicitante', 'verificacao_confirmada', 'status',
          'resposta', 'versao', 'criado_em', 'atualizado_em')
EVENT_FIELDS = ('id', 'solicitacao_id', 'versao', 'status', 'resposta',
                'professor_id', 'nome_professor', 'criado_em')
PAGE_SIZE = 50


class InvalidPrivacyRequest(ValueError):
    pass


def atendimento_config():
    def setting(name):
        return str(current_app.config.get(name, os.getenv(name, '')) or '').strip()
    controller = setting('ROAR_PRIVACY_CONTROLLER')
    contact = setting('ROAR_PRIVACY_CONTACT')
    enabled = setting('ROAR_PRIVACY_REQUESTS_ENABLED').lower() == 'true'
    available = enabled and bool(controller) and bool(contact)
    return {'disponivel': available, 'responsavel': controller if available else None,
            'contato': contact if available else None}


def failure(message, code, status):
    return jsonify(erro=message, code=code), status


def storage_failure(error):
    # Log the exception class only; descriptions and database errors are personal.
    current_app.logger.error('Solicitações de dados indisponíveis (%s)', type(error).__name__)
    return failure('Não foi possível acessar as solicitações. Tente novamente.',
                   'PRIVACY_REQUESTS_UNAVAILABLE', 503)


def rows(query):
    result = query.execute()
    return result.data or [] if result else []


def teacher_owns_student(aluno_id):
    teacher_id = getattr(request, 'professor_id', None)
    return teacher_id and bool(rows(supabase_admin.table('alunos').select('id')
        .eq('id', aluno_id).eq('professor_id', teacher_id).limit(1)))


def text_value(value, label, minimum=10):
    if not isinstance(value, str):
        raise InvalidPrivacyRequest(f'Informe {label}.')
    value = value.strip()
    if not minimum <= len(value) <= 2000 or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise InvalidPrivacyRequest(f'{label.capitalize()} deve ter entre {minimum} e 2000 caracteres.')
    return value


def request_uuid(value):
    if not isinstance(value, str):
        raise InvalidPrivacyRequest('Identificador de solicitação inválido.')
    try:
        parsed = UUID(value)
        if parsed.version != 4:
            raise ValueError()
        return str(parsed)
    except ValueError:
        raise InvalidPrivacyRequest('Identificador de solicitação inválido.') from None


def serialize_requests(items):
    events = rows(supabase_admin.table('solicitacoes_dados_eventos').select(','.join(EVENT_FIELDS))
        .in_('solicitacao_id', [row['id'] for row in items]).order('id')) if items else []
    by_request = {}
    for event in events:
        by_request.setdefault(event['solicitacao_id'], []).append({key: event.get(key) for key in EVENT_FIELDS})
    result = []
    for row in items:
        public = {key: row.get(key) for key in FIELDS if key != 'ordem'}
        public['protocolo'] = 'ROAR-' + row['id'].upper()
        public['eventos'] = by_request.get(row['id'], [])
        result.append(public)
    return result


def list_requests(aluno_id):
    cursor = request.args.get('antes')
    if set(request.args) - {'antes'} or (cursor is not None and
            (len(cursor) > 19 or not cursor.isascii() or not cursor.isdecimal() or not 0 < int(cursor) < 2**63)):
        return failure('Página de solicitações inválida.', 'INVALID_REQUEST_CURSOR', 400)
    query = supabase_admin.table('solicitacoes_dados').select(','.join(FIELDS)).eq('aluno_id', aluno_id)
    if cursor is not None:
        query = query.lt('ordem', int(cursor))
    items = rows(query.order('ordem', desc=True).limit(PAGE_SIZE + 1))
    next_cursor = items[PAGE_SIZE - 1]['ordem'] if len(items) > PAGE_SIZE else None
    return jsonify(solicitacoes=serialize_requests(items[:PAGE_SIZE]), proximo_cursor=next_cursor)


def intake_unavailable():
    return failure('O responsável e o canal oficial de atendimento ainda precisam ser configurados.',
                   'PRIVACY_REQUESTS_NOT_CONFIGURED', 503)


@solicitacoes_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@solicitacoes_bp.get('/privacidade/atendimento')
def atendimento():
    return jsonify(atendimento_config())


@solicitacoes_bp.get('/alunos/solicitacoes-dados')
@token_obrigatorio
def student_requests():
    aluno_id = getattr(request, 'aluno_id', None)
    if not aluno_id:
        return failure('O acompanhamento é exclusivo do próprio aluno.', 'STUDENT_ACCESS_REQUIRED', 403)
    try:
        if not rows(supabase_admin.table('alunos').select('id').eq('id', aluno_id).eq('ativo', True).limit(1)):
            return failure('Aluno indisponível.', 'STUDENT_ACCESS_DENIED', 403)
        return list_requests(aluno_id)
    except Exception as error:
        return storage_failure(error)


@solicitacoes_bp.route('/professores/alunos/<int:aluno_id>/solicitacoes-dados', methods=['GET', 'POST'])
@token_obrigatorio
def teacher_requests(aluno_id):
    if not getattr(request, 'professor_id', None):
        return failure('O atendimento deve ser feito pelo professor da turma.', 'TEACHER_ACCESS_REQUIRED', 403)
    try:
        if not teacher_owns_student(aluno_id):
            return failure('Aluno indisponível para este professor.', 'STUDENT_ACCESS_DENIED', 403)
        if request.method == 'GET':
            return list_requests(aluno_id)
        if not atendimento_config()['disponivel']:
            return intake_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'id', 'tipo', 'descricao', 'solicitante', 'verificacao_confirmada'}:
            raise InvalidPrivacyRequest('Informe somente os campos da solicitação.')
        if body['tipo'] not in ('correcao', 'exclusao') or body['solicitante'] not in ('titular', 'responsavel'):
            raise InvalidPrivacyRequest('Tipo de solicitação ou solicitante inválido.')
        if body['verificacao_confirmada'] is not True:
            raise InvalidPrivacyRequest('Confirme a identidade, o vínculo e a autorização antes de registrar.')
        payload = {**body, 'id': request_uuid(body['id']),
                   'descricao': text_value(body['descricao'], 'a descrição'),
                   'aluno_id': aluno_id, 'professor_abertura_id': request.professor_id,
                   'atendido_por_id': request.professor_id, 'status': 'recebida', 'resposta': '', 'versao': 1}
        inserted = rows(supabase_admin.table('solicitacoes_dados').upsert(payload, on_conflict='id', ignore_duplicates=True))
        existing = inserted or rows(supabase_admin.table('solicitacoes_dados').select(','.join(FIELDS))
            .eq('id', payload['id']).eq('aluno_id', aluno_id).limit(1))
        immutable = ('id', 'aluno_id', 'professor_abertura_id', 'tipo', 'descricao', 'solicitante', 'verificacao_confirmada')
        if not existing or any(existing[0].get(key) != payload[key] for key in immutable):
            return failure('Este identificador já foi usado em outro pedido. Atualize a lista.', 'REQUEST_ID_CONFLICT', 409)
        return jsonify(solicitacao=serialize_requests(existing)[0]), 201 if inserted else 200
    except InvalidPrivacyRequest as error:
        return failure(str(error), 'INVALID_PRIVACY_REQUEST', 400)
    except Exception as error:
        return storage_failure(error)


@solicitacoes_bp.patch('/professores/alunos/<int:aluno_id>/solicitacoes-dados/<uuid:solicitacao_id>')
@token_obrigatorio
def answer_request(aluno_id, solicitacao_id):
    if not getattr(request, 'professor_id', None):
        return failure('O atendimento deve ser feito pelo professor da turma.', 'TEACHER_ACCESS_REQUIRED', 403)
    try:
        if not teacher_owns_student(aluno_id):
            return failure('Aluno indisponível para este professor.', 'STUDENT_ACCESS_DENIED', 403)
        if not atendimento_config()['disponivel']:
            return intake_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'status', 'resposta', 'versao'}:
            raise InvalidPrivacyRequest('Informe o status, a resposta e a versão atual.')
        if body['status'] not in ('em_analise', 'respondida') or type(body['versao']) is not int or not 1 <= body['versao'] < 2**31 - 1:
            raise InvalidPrivacyRequest('Status ou versão inválida.')
        answer = text_value(body['resposta'], 'a resposta', 10 if body['status'] == 'respondida' else 0)
        if body['status'] != 'respondida' and answer:
            raise InvalidPrivacyRequest('Registre a resposta somente ao concluir o atendimento.')
        identifier = str(solicitacao_id)
        found = rows(supabase_admin.table('solicitacoes_dados').select(','.join(FIELDS))
            .eq('id', identifier).eq('aluno_id', aluno_id).limit(1))
        if not found:
            return failure('Solicitação não encontrada.', 'REQUEST_NOT_FOUND', 404)
        previous = found[0]
        if previous['versao'] != body['versao'] or previous['status'] == 'respondida' or previous['status'] == body['status']:
            return failure('Esta solicitação já foi atualizada. Recarregue a lista.', 'REQUEST_VERSION_CONFLICT', 409)
        updated = rows(supabase_admin.table('solicitacoes_dados').update({
            'status': body['status'], 'resposta': answer, 'versao': body['versao'] + 1,
            'atendido_por_id': request.professor_id, 'atualizado_em': datetime.now(timezone.utc).isoformat(),
        }).eq('id', identifier).eq('aluno_id', aluno_id).eq('versao', body['versao']))
        if not updated:
            return failure('Outra atualização ocorreu. Recarregue a lista.', 'REQUEST_VERSION_CONFLICT', 409)
        return jsonify(solicitacao=serialize_requests(updated)[0])
    except InvalidPrivacyRequest as error:
        return failure(str(error), 'INVALID_PRIVACY_REQUEST', 400)
    except Exception as error:
        return storage_failure(error)
