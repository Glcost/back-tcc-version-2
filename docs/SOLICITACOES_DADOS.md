# Solicitações de correção e exclusão

O fluxo registra pedidos e respostas institucionais. Não executa correção,
exclusão, anonimização ou remoção de contas. Não envia e-mails ou notificações.

## Uso

No perfil de um aluno, o professor encontra **Gerenciar dados** para as cópias
JSON/PDF e **Solicitações de dados** para atendimento. Somente o professor
atualmente vinculado ao aluno pode registrar e responder. Contas desativadas
podem ser atendidas pelo professor por essas mesmas rotas; seus tokens antigos
não dão acesso ao acompanhamento do aluno.

O professor informa tipo, descrição e solicitante, confirmando manualmente
identidade, vínculo e autorização. O checkbox é uma declaração do professor;
não é uma verificação automática de documentos. A instituição precisa definir
o procedimento de conferência e quem autoriza cada decisão.

O aluno consulta seus protocolos, status, descrição, resposta e histórico em
**Configurações > Gerenciar dados**. Não registra pedidos diretamente nem baixa
exportações. Não existe conta de responsável. A entrega da resposta ao
responsável continua sendo responsabilidade do atendimento institucional.

Estados permitidos: recebida → em análise → respondida, ou recebida →
respondida. A resposta final exige texto e o pedido concluído não é reaberto.
A decisão e sua justificativa ficam visíveis ao aluno, como informado na tela.

## Ativação pendente

O responsável pelo projeto informou que instituição/pessoa responsável e canal
oficial ainda serão definidos. A publicação mantém o atendimento desativado.
As exportações existentes e a consulta de pedidos já registrados independem
dessa ativação. Para liberar criação e respostas, configurar no servidor:

```
ROAR_PRIVACY_REQUESTS_ENABLED=true
ROAR_PRIVACY_CONTROLLER=<instituição ou pessoa definida pela equipe>
ROAR_PRIVACY_CONTACT=<canal oficial definido pela equipe>
```

Os três valores são exigidos. Não usar os contatos fictícios dos testes em
produção. Pausar o atendimento não apaga pedidos existentes. O canal e a
identificação configurados serão públicos por `/privacidade/atendimento`.

## Persistência e autorização

Aplicar a migração `privacy_request_workflow` antes de publicar o frontend.
Ela adiciona `solicitacoes_dados` e `solicitacoes_dados_eventos`, ambas com RLS
e sem acesso para PUBLIC, anon e authenticated. Somente a API usa o cliente
privado, com vínculo e perfil verificados antes das consultas.

Um trigger em `roar_private`, com SECURITY INVOKER e search_path fixo, valida
novamente o professor vinculado e as transições, mantém os dados originais e
grava o evento na mesma transação. Registra ID e nome profissional do atendente
naquele momento. A API não tem permissões de UPDATE/DELETE nos eventos nem de
DELETE nos pedidos. Isso não torna o banco imutável para seu proprietário.

O cliente gera UUID v4 e o preserva ao repetir uma tentativa na mesma tela.
Upsert com `ignore_duplicates=True` e comparação dos campos originais impede
duplicação ou sobrescrita com o mesmo identificador. Atualizações incluem a
versão anterior no WHERE; conflitos exigem consultar novamente, sem repetição
automática. Não há persistência dos textos em localStorage.

A listagem retorna 50 pedidos por página e no máximo três eventos por pedido.
O cursor usa a sequência `ordem`, evitando omissões por paginação padrão. Os
textos são apresentados com textContent. Respostas privadas usam no-store.
Fechar o perfil ou o diálogo invalida respostas tardias da interface.

## Limites e decisões pendentes

- Definir controlador, canal, verificação e delegação de atendimento antes da ativação.
- Definir prazos de atendimento e retenção, sem confundir desativação com eliminação.
- Definir procedimento para efetivar e verificar correções/exclusões em todas
  as categorias, mídias, cópias e fornecedores. Os FKs desta etapa preservam o
  vínculo com o pedido; uma futura exclusão física precisa tratar também a
  retenção ou anonimização dos registros de atendimento.
- A exportação atual inclui cadastro e histórico, com escopo limitado; não é
  uma cópia integral de todas as categorias nem uma implementação completa
  de todos os direitos da LGPD.
- O acesso de um professor que perdeu o vínculo é recusado. A instituição
  precisa tratar transferência de turma e atendimento externo ao sistema.

## Evidências

`tests/test_privacy_requests.py` exercita rotas Flask/JWT reais com duas turmas
fictícias: configuração, autorização, entrada inválida, repetição, paginação,
status, versões, falhas e ausência de alteração do cadastro. O frontend inclui
`tools/check_privacy_requests_database.cjs`, com PostgreSQL descartável PGlite:
permissões, trigger real, atomicidade de eventos, duplicação, transições e
proteção do histórico. Não simula múltiplas conexões simultâneas.

`tools/check_privacy_requests_browser.cjs` cobre 1280/390 px, teclado, confirmação,
tentativa sem resposta, conflito, texto malicioso, consulta do aluno, bloqueio
de atendimento não configurado e troca de perfil com resposta atrasada.

| Referência | Recurso | Evidência |
| --- | --- | --- |
| LGPD, art. 6º, III | Coleta restrita ao pedido, sem anexos de documentos | Formulário limitado, validação e orientação de minimização |
| LGPD, art. 9º | Identificação e contato do atendimento | Configuração obrigatória e aviso quando ausente |
| LGPD, art. 18, III, IV, VI e §§ 3º–4º | Registro de correção/avaliação de exclusão e resposta | Protocolo, status e histórico; execução institucional separada |
| LGPD, art. 46 | Restrição de acesso aos pedidos | RLS, permissões privadas, JWT e isolamento por turma |

Referência conferida em 06/11/2026: [LGPD, texto oficial atualizado](https://www2.camara.leg.br/legin/fed/lei/2018/lei-13709-14-agosto-2018-787077-normaatualizada-pl.html).
O repositório [ctresb/leis](https://github.com/ctresb/leis) auxilia a organização
das referências. Essas evidências não comprovam conformidade integral.
