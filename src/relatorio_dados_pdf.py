"""Render an authorized student export in memory, without external services."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


BLUE = colors.HexColor('#28599A')
INK = colors.HexColor('#1C2837')
MUTED = colors.HexColor('#526176')
PALE = colors.HexColor('#EDF5FC')
BORDER = colors.HexColor('#D9E2EB')
BRASILIA = timezone(timedelta(hours=-3))
WIDTH = 174 * mm


def _catalogo(database, table, fields, ids):
    result = {}
    ids = sorted(set(ids))
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        cursor = 0
        while True:
            rows = (database.table(table).select(fields).in_('id', batch)
                    .gt('id', cursor).order('id').limit(100).execute()).data or []
            if not rows:
                break
            next_cursor = rows[-1]['id']
            if next_cursor <= cursor:
                raise RuntimeError('Invalid catalog cursor')
            result.update({row['id']: row for row in rows})
            cursor = next_cursor
            if cursor >= batch[-1]:
                break
    return result


def buscar_catalogo_relatorio(database, historico):
    ids = [row['atividade_id'] for row in historico if row.get('atividade_id')]
    atividades = _catalogo(database, 'atividades', 'id, modulo_id, palavra_chave, ordem_sequencia', ids)
    modulos = _catalogo(database, 'modulos', 'id, nome',
                       [row['modulo_id'] for row in atividades.values() if row.get('modulo_id')])
    return atividades, modulos


def _texto(value):
    return escape(str(value)) if value is not None and str(value).strip() else 'Não informado'


def _numero(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def _tempo(value):
    if value is None:
        return 'Não informado'
    minutes, seconds = divmod(value, 60)
    return f'{int(minutes)} min {seconds:g} s' if minutes else f'{seconds:g} s'


def _data(value):
    if not value:
        return 'Não informada'
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        suffix = ''
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(BRASILIA)
        else:
            suffix = ' (sem fuso)'
        return parsed.strftime('%d/%m/%Y %H:%M') + suffix
    except (ValueError, TypeError):
        return 'Data não informada'


def gerar_relatorio_pdf(exportacao, atividades, modulos):
    cadastro = exportacao['cadastro']
    historico = exportacao['historico_atividades']
    meta = exportacao['exportacao']
    styles = {
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9, leading=13, textColor=INK, spaceAfter=0),
        'small': ParagraphStyle('small', fontName='Helvetica', fontSize=8, leading=11, textColor=MUTED),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=BLUE, spaceBefore=16, spaceAfter=8, keepWithNext=True),
        'head': ParagraphStyle('head', fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.white),
        'center': ParagraphStyle('center', fontName='Helvetica', fontSize=8, leading=11, textColor=INK, alignment=TA_CENTER),
    }

    def p(value, style='body'):
        return Paragraph(_texto(value), styles[style])

    def field(label, value):
        return Paragraph(f'<font color="#526176">{_texto(label)}</font><br/><b>{_texto(value)}</b>', styles['body'])

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                                 topMargin=39*mm, bottomMargin=24*mm,
                                 title='ROAR - Relatório do aluno', author='ROAR')

    def page_frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(PALE)
        canvas.rect(0, A4[1]-30*mm, A4[0], 30*mm, stroke=0, fill=1)
        canvas.setFillColor(BLUE)
        canvas.setFont('Helvetica-Bold', 22)
        canvas.drawString(18*mm, A4[1]-16*mm, 'ROAR')
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(A4[0]-18*mm, A4[1]-13*mm, 'Relatório do aluno')
        canvas.setFillColor(MUTED)
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(A4[0]-18*mm, A4[1]-19*mm, 'Emissão: ' + _data(meta.get('gerada_em')))
        canvas.setStrokeColor(BORDER)
        canvas.line(18*mm, 19*mm, A4[0]-18*mm, 19*mm)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(18*mm, 14*mm, 'Dados pessoais - entregue somente ao solicitante verificado.')
        canvas.drawRightString(A4[0]-18*mm, 14*mm, f'Página {doc.page}')
        canvas.restoreState()

    nivel = cadastro.get('nivel_suporte_tea')
    suporte = f'Nível {nivel}' if nivel in (1, 2, 3) else 'Não informado'
    status = {True:'Ativo', False:'Desativado'}.get(cadastro.get('ativo'), 'Não informado')
    story = [p('Cadastro atual', 'section')]
    profile = Table([
        [field('Aluno', cadastro.get('nome')), field('Ano escolar', cadastro.get('ano_escolar'))],
        [field('E-mail', cadastro.get('email')), field('Situação da conta', status)],
        [field('Modo de aprendizagem', cadastro.get('modo_aprendizagem')), field('Nível de suporte TEA', suporte)],
    ], colWidths=[WIDTH*.6, WIDTH*.4], hAlign='LEFT')
    profile.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BACKGROUND', (0,0), (-1,-1), PALE),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 9), ('BOTTOMPADDING', (0,0), (-1,-1), 9),
        ('LINEBELOW', (0,0), (-1,-2), .5, colors.white),
    ]))
    story.extend([profile, p('Resumo dos registros', 'section')])
    tempos = [number for row in historico if (number := _numero(row.get('tempo_segundos'))) is not None]
    erros = [number for row in historico if (number := _numero(row.get('quantidade_erros'))) is not None]
    ids = {row.get('atividade_id') for row in historico if row.get('atividade_id') is not None}
    concluidas = {row['atividade_id'] for row in historico if row.get('concluido') is True and row.get('atividade_id') is not None}
    summary = Table([
        [field('Registros no histórico', len(historico)), field('Atividades distintas', len(ids)), field('Atividades concluídas', len(concluidas))],
        [field('Erros registrados', f'{sum(erros):g}' if erros else 'Não informado'),
         field('Tempo registrado', _tempo(sum(tempos)) if tempos else 'Não informado'), field('XP atual', cadastro.get('xp_total'))],
    ], colWidths=[WIDTH/3]*3, hAlign='LEFT')
    summary.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOX', (0,0), (-1,-1), .6, BORDER),
        ('INNERGRID', (0,0), (-1,-1), .4, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 10), ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.extend([summary, Spacer(1, 6), p(
        f'Totais dos valores informados: erros em {len(erros)} de {len(historico)} registros; '
        f'tempo em {len(tempos)} de {len(historico)}. Atividades concluídas são contadas uma única vez.', 'small'),
        p('Histórico das atividades', 'section')])
    if not historico:
        story.append(p('Ainda não há atividades registradas para este aluno.'))
    else:
        rows = [[p(label, 'head') for label in ['Data', 'Atividade / módulo', 'Conclusão', 'Erros', 'Tempo']]]
        for row in historico:
            activity = atividades.get(row.get('atividade_id'), {})
            module = modulos.get(activity.get('modulo_id'), {})
            title = activity.get('palavra_chave') or f"Atividade sem título (código {row.get('atividade_id')})"
            details = [_texto(title), _texto(module.get('nome'))]
            if activity.get('ordem_sequencia') is not None:
                details.append('Etapa ' + _texto(activity['ordem_sequencia']))
            details.append('Modo: ' + _texto(row.get('modo_utilizado')))
            activity_cell = Paragraph('<b>' + details[0] + '</b><br/>' + '<br/>'.join(details[1:]), styles['small'])
            completed = 'Concluída' if row.get('concluido') is True else 'Não concluída' if row.get('concluido') is False else 'Não informada'
            number = _numero(row.get('quantidade_erros'))
            rows.append([p(_data(row.get('data_hora')), 'small'), activity_cell, p(completed, 'small'),
                         p(f'{number:g}' if number is not None else '-', 'center'), p(_tempo(_numero(row.get('tempo_segundos'))), 'small')])
        history_table = LongTable(rows, colWidths=[29*mm, 72*mm, 27*mm, 15*mm, 31*mm],
                                  repeatRows=1, hAlign='LEFT')
        history_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), BLUE), ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, PALE]),
            ('LEFTPADDING', (0,0), (-1,-1), 7), ('RIGHTPADDING', (0,0), (-1,-1), 7),
            ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('LINEBELOW', (0,0), (-1,0), .6, BLUE),
        ]))
        story.append(history_table)
    requester = 'Próprio aluno' if meta.get('solicitante') == 'titular' else 'Responsável com vínculo verificado'
    story.extend([p('Identificação da emissão', 'section'),
        p(f"Solicitante: {requester}. Professor emissor: {meta.get('professor_id')}."),
        p('Identidade e autorização confirmadas manualmente pelo professor.', 'small'),
        p('Identificador: ' + str(meta.get('id')), 'small'), Spacer(1, 7),
        p('O relatório apresenta o cadastro atual e os registros disponíveis no momento da emissão. '
          'Erros e tempos são medidas registradas nas atividades. Horários com fuso são apresentados em Brasília (UTC-3).', 'small')])
    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return stream.getvalue()
