# Melhorias dos jogos e confiabilidade

## Preparação do banco

Aplique **migrations/20261104_learning_reliability.sql** com uma conta administrativa do banco **antes** de publicar esta versão da API. A migração é aditiva: cria três tabelas protegidas e quatro funções; não remove alunos, histórico, XP ou inventário existentes. Execute primeiro em homologação e mantenha o procedimento normal de backup do projeto.

O servidor precisa de `SUPABASE_SECRET_KEY`, usada somente pelo cliente `supabase_admin`. Não exponha essa chave no frontend. `anon` e `authenticated` não recebem acesso às tabelas nem execução das funções. As rotas verificam o aluno do token ou a responsabilidade do professor antes de usar o cliente administrativo.

Sem cliente administrativo ou migração, as novas operações retornam **503 / LEARNING_STORAGE_UNAVAILABLE**. Não há retorno silencioso ao salvamento antigo não atômico. A migração foi testada em PostgreSQL descartável e aplicada em 04/11/2026 ao projeto Roar db pelo painel autenticado do Supabase. A estrutura existente foi conferida antes da aplicação. A atualização adiciona tabelas e funções; não altera os registros de alunos nem os saldos existentes.

## Loja e progresso

- `POST /alunos/desempenho` exige o token e encaminha ao mesmo fluxo de `POST /atividades/progresso`. O ID do aluno vem do token; um ID diferente no corpo é rejeitado.
- `/alunos/loja-lex` mantém GET de saldo e POST com `{acao: "comprar"|"equipar", skin_id}`. Equipar exige posse (o mascote inicial gratuito é considerado adquirido). Comprar um Dino já adquirido não desconta novamente.
- Compra, inventário e equipamento são uma transação. As recompensas de atividades usam o mesmo bloqueio de saldo do aluno, evitando sobrescrita de XP por essas operações concorrentes.
- Progresso e XP são gravados juntos. Repetir `id_tentativa` devolve a resposta já gravada, sem duplicar recompensa ou métricas. Clientes novos devem gerar um UUID e persistir até o salvamento ser confirmado.
- Uma nova tentativa de atividade já concluída registra novas evidências por palavra, sem XP adicional e sem duplicar o registro de conclusão anterior. Históricos antigos não são convertidos em acertos ou ajudas inventados.

Payload adicional opcional de `/atividades/progresso`:

```json
{
  "atividade_id": 1,
  "quantidade_erros": 0,
  "tempo_segundos": 15,
  "concluido": true,
  "id_tentativa": "00000000-0000-4000-8000-000000000001",
  "palavras": [{"palavra": "HEAD", "acertos": 1, "erros": 0, "ajudas": 1}]
}
```

## Preferências por aluno

- `GET /alunos/preferencias-jogos`: o aluno consulta suas próprias preferências.
- `GET/PATCH /professores/alunos/<id>/preferencias-jogos`: somente o professor responsável consulta/altera.
- O objeto é retornado diretamente: `pieceCount: null|2|4|6`, `showHints: boolean`, `memoryPreviewSeconds: 3|5|8|10`, `advanceDelaySeconds: 1|2|3|5`.
- Padrões: `null`, `true`, `5`, `1`. Quantidade `null` mantém a regra do perfil. PATCH aceita subconjunto dos campos e mescla sob bloqueio do aluno.

## Relatório por palavra

`GET /relatorios/aluno/<id>/palavras` autoriza somente o próprio aluno ou seu professor. Resposta `{aluno_id, palavras:[{palavra,acertos,erros,ajudas,tentativas,ultima_pratica,precisa_revisao}]}`. `precisa_revisao` usa somente a **última prática registrada da palavra**: sugere revisão quando houve erro, ajuda ou nenhum acerto nessa prática. Uma prática posterior com acerto sem erro nem ajuda retira a sugestão. Os totais históricos de acertos, erros e ajudas continuam intactos. O instante real de registro e uma sequência crescente resolvem a ordem, inclusive em gravações próximas. Não é diagnóstico, nem avaliação clínica. As contagens são evidências enviadas pelo cliente, não uma avaliação antifraude. O relatório retorna uma lista vazia quando não há dados novos.

## Testes

```text
python -m pip install Flask PyJWT
python -m unittest discover -s tests -v
```

Os testes de rota executam Flask e o decorador JWT reais com banco simulado, sem inicializar o cliente Supabase e sem acessar a rede. Verificam autenticação, propriedade do aluno, validação de preferências/evidências, a rota antiga protegida e erro fechado quando a migração está ausente.

Em um PostgreSQL **descartável**, execute em sequência `tests/learning_fixture.sql`, `migrations/20261104_learning_reliability.sql` e `tests/learning_transactions.sql` com parada no primeiro erro. **A fixture é somente de teste; nunca executar no banco do projeto.** O workflow `.github/workflows/backend-checks.yml` executa isso em PostgreSQL 16 de um serviço temporário, além dos testes Python. Os cenários SQL verificam permissões, compra única, propriedade, idempotência, revisão sem novo XP e rollback de histórico/inventário quando uma atualização falha.

## Verificação após publicação

`GET /health/learning` retorna `200 {"status":"ready"}` quando o cliente administrativo e o relatório protegido estão disponíveis. A consulta usa um ID negativo e não lê dados de alunos. Quando a dependência está indisponível, retorna 503 sem divulgar detalhes de configuração.
