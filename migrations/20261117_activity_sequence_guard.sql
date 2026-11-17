begin;

create or replace function public.roar_register_progress(
  p_aluno_id bigint,
  p_atividade_id bigint,
  p_quantidade_erros integer,
  p_tempo_segundos integer,
  p_concluido boolean,
  p_id_tentativa uuid,
  p_palavras jsonb default '[]'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  student public.alunos%rowtype;
  saved jsonb;
  response jsonb;
  previous_completion boolean;
  pending_previous_activity boolean;
  activity_module_id bigint;
  activity_order bigint;
  reward integer := 0;
  word jsonb;
  status_code integer := 201;
begin
  select *
    into student
    from public.alunos
   where id = p_aluno_id
     and ativo = true
   for update;

  if not found then
    return jsonb_build_object(
      'erro', 'Aluno não encontrado.',
      'code', 'STUDENT_NOT_FOUND',
      'status', 404
    );
  end if;

  if p_id_tentativa is null
     or p_quantidade_erros is null
     or p_tempo_segundos is null
     or p_concluido is null
     or p_quantidade_erros not between 0 and 1000
     or p_tempo_segundos not between 0 and 86400
     or p_palavras is null
     or jsonb_typeof(p_palavras) <> 'array'
     or jsonb_array_length(p_palavras) > 128 then
    raise exception 'Invalid progress data';
  end if;

  select a.modulo_id, a.ordem_sequencia
    into activity_module_id, activity_order
    from public.atividades a
    join public.variacoes_atividades v
      on v.atividade_id = a.id
   where a.id = p_atividade_id
     and v.modo_alvo = student.modo_aprendizagem
   order by v.id
   limit 1;

  if not found then
    return jsonb_build_object(
      'erro', 'Atividade indisponível para este aluno.',
      'code', 'ACTIVITY_NOT_AVAILABLE_FOR_MODE',
      'status', 403
    );
  end if;

  select exists (
    select 1
      from public.atividades previous_activity
      join public.variacoes_atividades previous_variation
        on previous_variation.atividade_id = previous_activity.id
       and previous_variation.modo_alvo = student.modo_aprendizagem
     where previous_activity.modulo_id = activity_module_id
       and (
         previous_activity.ordem_sequencia < activity_order
         or (
           previous_activity.ordem_sequencia = activity_order
           and previous_activity.id < p_atividade_id
         )
       )
       and not exists (
         select 1
           from public.historico_desempenho completed
          where completed.aluno_id = p_aluno_id
            and completed.atividade_id = previous_activity.id
            and completed.concluido = true
       )
  ) into pending_previous_activity;

  if pending_previous_activity then
    return jsonb_build_object(
      'erro', 'Conclua as etapas anteriores antes de continuar.',
      'code', 'PREVIOUS_ACTIVITY_REQUIRED',
      'status', 409
    );
  end if;

  select resposta
    into saved
    from public.roar_progress_requests
   where aluno_id = p_aluno_id
     and id_tentativa = p_id_tentativa;

  if found then
    if (saved->'data'->>'atividade_id')::bigint <> p_atividade_id then
      return jsonb_build_object(
        'erro', 'A tentativa já pertence a outra atividade.',
        'code', 'ATTEMPT_ACTIVITY_MISMATCH',
        'status', 409
      );
    end if;

    return saved || jsonb_build_object('status', 200);
  end if;

  select exists (
    select 1
      from public.historico_desempenho
     where aluno_id = p_aluno_id
       and atividade_id = p_atividade_id
       and concluido = true
  ) into previous_completion;

  if p_concluido and previous_completion then
    status_code := 200;
  else
    insert into public.historico_desempenho (
      aluno_id,
      atividade_id,
      modo_utilizado,
      quantidade_erros,
      tempo_segundos,
      concluido
    ) values (
      p_aluno_id,
      p_atividade_id,
      student.modo_aprendizagem,
      p_quantidade_erros,
      p_tempo_segundos,
      p_concluido
    );

    if p_concluido then
      reward := greatest(10, 50 - p_quantidade_erros * 5);
    end if;
  end if;

  for word in select value from jsonb_array_elements(p_palavras) loop
    if jsonb_typeof(word) <> 'object'
       or not (word ?& array['palavra', 'acertos', 'erros', 'ajudas'])
       or jsonb_typeof(word->'palavra') <> 'string'
       or jsonb_typeof(word->'acertos') <> 'number'
       or jsonb_typeof(word->'erros') <> 'number'
       or jsonb_typeof(word->'ajudas') <> 'number'
       or length(btrim(word->>'palavra')) not between 1 and 100
       or (word->>'acertos')::integer not between 0 and 10000
       or (word->>'erros')::integer not between 0 and 10000
       or (word->>'ajudas')::integer not between 0 and 10000 then
      raise exception 'Invalid word evidence';
    end if;

    insert into public.aluno_palavras_pratica (
      aluno_id,
      id_tentativa,
      atividade_id,
      palavra,
      acertos,
      erros,
      ajudas
    ) values (
      p_aluno_id,
      p_id_tentativa,
      p_atividade_id,
      upper(btrim(word->>'palavra')),
      (word->>'acertos')::integer,
      (word->>'erros')::integer,
      (word->>'ajudas')::integer
    );
  end loop;

  update public.alunos
     set xp_total = coalesce(xp_total, 0) + reward
   where id = p_aluno_id
   returning * into student;

  response := jsonb_build_object(
    'mensagem', case
      when p_concluido and previous_completion
        then 'Atividade já concluída; revisão registrada sem XP adicional.'
      else 'Progresso registrado com sucesso.'
    end,
    'code', case
      when p_concluido and previous_completion
        then 'ACTIVITY_ALREADY_COMPLETED'
      else 'PROGRESS_REGISTERED'
    end,
    'status', status_code,
    'data', jsonb_build_object(
      'aluno_id', p_aluno_id,
      'atividade_id', p_atividade_id,
      'concluido', p_concluido,
      'primeira_conclusao', p_concluido and not previous_completion,
      'xp_ganho', reward,
      'xp_total', student.xp_total
    )
  );

  insert into public.roar_progress_requests (
    aluno_id,
    id_tentativa,
    atividade_id,
    resposta
  ) values (
    p_aluno_id,
    p_id_tentativa,
    p_atividade_id,
    response
  );

  return response;
end;
$$;

revoke all on function public.roar_register_progress(
  bigint, bigint, integer, integer, boolean, uuid, jsonb
) from public, anon, authenticated;
grant execute on function public.roar_register_progress(
  bigint, bigint, integer, integer, boolean, uuid, jsonb
) to service_role;

commit;
