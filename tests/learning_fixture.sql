-- TEST ONLY: deliberately tiny schema for transactional regression tests.
create role anon;
create role authenticated;
create role service_role;
create table public.alunos(id bigint primary key,professor_id bigint,ativo boolean not null default true,xp_total bigint not null default 0,skin_ativa_id bigint default 1,modo_aprendizagem text);
create table public.skins_lex(id bigint primary key,nome text,preco_xp bigint);
create table public.aluno_skins_lex(aluno_id bigint references alunos(id),skin_id bigint references skins_lex(id),unique(aluno_id,skin_id));
create table public.atividades(id bigint primary key,modulo_id bigint,ordem_sequencia integer);
create table public.variacoes_atividades(id bigint primary key,atividade_id bigint references atividades(id),modo_alvo text);
create table public.historico_desempenho(id bigint generated always as identity primary key,aluno_id bigint,atividade_id bigint,modo_utilizado text,quantidade_erros integer,tempo_segundos integer,concluido boolean,data_hora timestamptz default now());
insert into alunos(id,professor_id,xp_total,modo_aprendizagem) values(17,5,500,'Nível 1 - Suporte Visual Puro'),(18,6,0,'Nível 1 - Suporte Visual Puro');
insert into skins_lex values(1,'Clássico',0),(2,'Explorador',100),(3,'Astronauta',1000);
insert into atividades values(1,9,1),(2,9,2),(3,9,3);
insert into variacoes_atividades values(1,1,'Nível 1 - Suporte Visual Puro'),(2,2,'Nível 1 - Suporte Visual Puro'),(3,3,'Nível 1 - Suporte Visual Puro');
