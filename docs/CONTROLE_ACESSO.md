# Controle de acesso e proteção do banco

O ROAR autentica alunos e professores com JWTs próprios. Os navegadores usam
somente a API Flask. As consultas ao Supabase são feitas pelo cliente privado
do servidor, com `SUPABASE_SECRET_KEY`, e as rotas conferem o perfil e o vínculo
antes de consultar ou alterar dados. Essa chave não é enviada ao navegador.

## Camadas de proteção

- O cliente legado `supabase` aponta para o mesmo cliente privado de
  `supabase_admin`. Configuração ausente ou chave pública no lugar da privada
  impede a inicialização; não existe fallback anônimo.
- URLs com IDs de professor exigem o mesmo professor do token. Consultas de
  alunos incluem o professor responsável. Rotas do aluno usam a identidade do
  token e recusam IDs de outras pessoas.
- `/alunos/desempenho` delega para o salvamento atual, com as mesmas validações,
  identidade e transação de progresso. O modo de aprendizagem vem do cadastro.
- JWTs exigem sujeito positivo, perfil conhecido, emissão e expiração. As
  respostas pessoais são privadas e não devem ser armazenadas em cache.
- Erros retornados ao cliente não incluem detalhes internos de banco ou conexão.
- A migração `restrict_direct_database_access` habilita RLS nas 20 tabelas do
  aplicativo, revoga acesso direto de `anon`, `authenticated` e `PUBLIC`, e
  preserva as permissões da API em `service_role`.
- Os catálogos também passam pela API autenticada. O acesso aos arquivos de
  mídia existentes não é alterado por essa migração.
- A política que permitia a qualquer cliente alterar `professor_modulos` é
  removida. As funções públicas e sequências ficam reservadas ao servidor.
- Privilégios padrão do proprietário `postgres` deixam de liberar novos
  objetos para clientes. O padrão global de EXECUTE para PUBLIC também é
  revogado, pois um REVOKE apenas no schema não remove esse padrão do PostgreSQL.

RLS sem políticas para clientes é intencional neste modelo: essas tabelas são
acessadas pela API autorizada, não por sessões do Supabase Auth. Não se devem
criar políticas com `auth.uid()` para os IDs inteiros dos JWTs próprios do ROAR.
A chave privada ignora RLS; por isso a autorização das rotas continua obrigatória.

## Publicação

1. Executar os testes locais e publicar a API que usa o cliente privado.
2. Conferir a publicação e `/health/learning` antes de restringir o banco.
3. Aplicar a migração no projeto Supabase correto, em transação com timeout de
   bloqueio, para evitar uma alteração parcial.
4. Conferir permissões, RLS, RPCs e funcionamento da API depois da migração.
5. Manter os arquivos locais da migração com a versão registrada no Supabase.

A migração não exclui nem reescreve cadastros ou históricos. Em caso de erro de
acesso, revisar a configuração do servidor e o GRANT necessário; reabrir acesso
anônimo às tabelas pessoais não é a correção prevista.

## Evidências e testes

Aplicação em produção concluída em 06/11/2026. A consulta de metadados confirmou
20 tabelas protegidas pela migração de segurança, zero sem RLS e zero com
SELECT anônimo ou UPDATE de clientes autenticados. O advisor passou a retornar
somente avisos informativos de RLS sem políticas, intencionais neste modelo.
O fluxo de solicitações adiciona outras duas tabelas privadas por migração própria.

Foram executadas 35 verificações na API antes da restrição e 48 depois, com
duas turmas e contas inteiramente fictícias. Incluíram login, conteúdo,
relatórios, JSON/PDF, preferências, progresso sem XP duplicado e bloqueio de
alunos desativados. As contas temporárias foram removidas e a ausência delas
foi confirmada, sem excluir ou exportar cadastros reais.

- `tests/test_access_control.py`: aplicação e blueprints reais, JWTs reais,
  banco simulado e duas turmas fictícias. Inclui login, lista, leitura própria,
  bloqueio entre turmas, edição, desativação, PIN, relatórios, exportações,
  progresso legado, tokens inválidos e alunos desativados.
- A suíte da entrega de segurança continha 63 testes: 59 executados com sucesso
  e quatro testes de concorrência não executados por falta de um
  PostgreSQL local descartável. Esses quatro não usam o banco hospedado.
- `tools/check_database_access.cjs`, no frontend: PostgreSQL em memória com
  PGlite. Verifica a migração duas vezes, negação de tabelas, sequências e RPCs
  a clientes, proteção de objetos futuros e funcionamento de progresso/loja
  pelo servidor. PGlite tem uma conexão e não substitui testes de concorrência.
- Testes de navegador cobrem o PDF com Flask/JWT e dados fictícios.

## Relação com referências legais

| Referência | Medida no ROAR | Evidência |
| --- | --- | --- |
| LGPD, art. 6º, VII e VIII | Segurança e prevenção no acesso aos dados | Cliente privado, bloqueio de acesso direto e respostas sem detalhes internos |
| LGPD, art. 46 | Medidas contra acesso e alteração não autorizados | Migração de permissões/RLS e testes entre turmas |
| LGPD, arts. 5º, II, e 11 | Acesso restrito às informações sobre suporte TEA | Tabela privada e consulta após autorização |
| LGPD, art. 14 | Proteção das informações dos alunos | Identidade do token e isolamento por turma |

O repositório [ctresb/leis](https://github.com/ctresb/leis) serve para localizar
e organizar referências. A conferência jurídica utiliza a
[LGPD na fonte oficial](https://www2.camara.leg.br/legin/fed/lei/2018/lei-13709-14-agosto-2018-787077-normaatualizada-pl.html).
Essas medidas técnicas não comprovam, isoladamente, conformidade integral.

Referências técnicas: [segurança da Data API](https://supabase.com/docs/guides/api/securing-your-api)
e [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).
