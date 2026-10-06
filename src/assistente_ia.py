import json
import os

from google import genai
from google.genai import types
from pydantic import BaseModel


class AssistenteIAIndisponivel(RuntimeError):
    """Indica que o serviço de IA não pôde gerar a análise."""


class AnalisePedagogica(BaseModel):
    resumo: str
    pontos_positivos: list[str]
    dificuldades: list[str]
    sugestoes: list[str]
    aviso: str


def _obter_configuracao():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv(
        "GEMINI_MODEL",
        "gemini-2.5-flash-lite",
    ).strip()

    if not api_key:
        raise AssistenteIAIndisponivel(
            "A chave do Gemini não está configurada."
        )

    if not model:
        raise AssistenteIAIndisponivel(
            "O modelo do Gemini não está configurado."
        )

    return api_key, model


def gerar_analise_aluno(metricas: dict) -> dict:
    if not isinstance(metricas, dict) or not metricas:
        raise ValueError(
            "As métricas do aluno são obrigatórias."
        )

    api_key, model = _obter_configuracao()

    client = genai.Client(api_key=api_key)

    metricas_json = json.dumps(
        metricas,
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
Você é o Assistente Pedagógico do sistema ROAR.

O ROAR é uma plataforma educacional de inglês que utiliza
atividades visuais, auditivas e interativas.

Analise exclusivamente as métricas pedagógicas anônimas
fornecidas abaixo.

Regras obrigatórias:

1. Não faça diagnóstico médico, psicológico ou clínico.
2. Não afirme que o aluno possui uma deficiência ou transtorno.
3. Não substitua a avaliação de professores, responsáveis ou
   profissionais especializados.
4. Use linguagem respeitosa, clara e objetiva.
5. Não invente informações ausentes nas métricas.
6. Considere que poucos registros podem não ser suficientes
   para conclusões confiáveis.
7. Produza sugestões práticas que o professor possa aplicar
   nas próximas atividades.
8. Cada lista deve conter no máximo quatro itens.
9. Não mencione que você recebeu dados anônimos.
10. Responda em português do Brasil.

Métricas pedagógicas:

{metricas_json}
""".strip()

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1200,
                response_mime_type="application/json",
                response_schema=AnalisePedagogica,
            ),
        )

        if not response.text:
            raise AssistenteIAIndisponivel(
                "O Gemini não retornou uma análise."
            )

        analise = AnalisePedagogica.model_validate_json(
            response.text
        )

        return analise.model_dump()

    except AssistenteIAIndisponivel:
        raise

    except Exception as error:
        raise AssistenteIAIndisponivel(
            "Não foi possível gerar a análise neste momento."
        ) from error