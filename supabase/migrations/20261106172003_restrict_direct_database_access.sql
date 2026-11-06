-- Prerequisite: deploy the API using its private server client before applying.
-- The application authenticates its own JWTs; clients never connect to these
-- tables directly. Tenant ownership is checked by the API before server queries.
-- This migration changes access only. It does not delete or rewrite user data.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

revoke create on schema public from public, anon, authenticated;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'alunos','professores','avaliacao_inicial','historico_desempenho',
    'personalizacao_aluno','aluno_suporte_tea','aluno_preferencias_jogos',
    'aluno_palavras_pratica','roar_progress_requests','recompensas_missoes',
    'aluno_skins_lex','recuperacoes_senha_professor','verificacoes_email_professor',
    'professor_modulos','atividades','variacoes_atividades','itens_modulo',
    'modulos','skins_lex','backup_historico_desempenho_20260915'
  ] loop
    if to_regclass(format('public.%I', table_name)) is null then
      raise exception 'Required application table is missing: %', table_name;
    end if;
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on table public.%I from public, anon, authenticated', table_name);
    execute format('grant select, insert, update, delete on table public.%I to service_role', table_name);
  end loop;
end $$;

-- A previous policy allowed every role to change any teacher's module settings.
drop policy if exists "Mudar o valor" on public.professor_modulos;

revoke all on all sequences in schema public from public, anon, authenticated;
grant usage, select on all sequences in schema public to service_role;

-- Includes rls_auto_enable(), previously executable by anonymous clients.
-- Existing protected progress, preferences, shop and reports remain server-only.
revoke all on all functions in schema public from public, anon, authenticated;
grant execute on all functions in schema public to service_role;

-- Application objects are created by postgres. Future migrations must opt in
-- explicitly to any direct client access rather than inherit broad defaults.
alter default privileges for role postgres in schema public
  revoke all on tables from public, anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from public, anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on functions from public, anon, authenticated;
-- PostgreSQL's built-in PUBLIC EXECUTE default is global. A schema-local
-- REVOKE alone cannot remove it from functions created in a later migration.
alter default privileges for role postgres
  revoke execute on functions from public;
alter default privileges for role postgres in schema public
  grant select, insert, update, delete on tables to service_role;
alter default privileges for role postgres in schema public
  grant usage, select on sequences to service_role;
alter default privileges for role postgres in schema public
  grant execute on functions to service_role;

notify pgrst, 'reload schema';
commit;
