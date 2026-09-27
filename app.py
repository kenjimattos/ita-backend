import os
import time

from fastapi import FastAPI
from google import genai
from google.cloud import bigquery
from pydantic import BaseModel

app = FastAPI()
bq = bigquery.Client()

TABELA = os.environ["TABLE_NAME"]

# gemini-3.x só está disponível na location "global" do Vertex AI
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
llm = genai.Client(
    vertexai=True,
    project=os.environ.get("GOOGLE_CLOUD_PROJECT", "batalha-time-01-97zr"),
    location=os.environ.get("GEMINI_LOCATION", "global"),
)

INSTRUCOES = """Você é um assistente financeiro do Itaú.
Responda em português, de forma curta e direta, usando apenas as transações fornecidas.
Valores negativos são saídas; positivos são entradas."""


def buscar_transacoes(id_usuario: str, limite: int = 50):
    query = f"""
        SELECT anomesdia, tipo, descr, vlr, nom_cate_macro, nom_cate_micro, saldo_apos
        FROM `{TABELA}`
        WHERE id_usuario = @id
        ORDER BY anomesdia DESC
        LIMIT {int(limite)}
    """
    job = bq.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", id_usuario)]
        ),
    )
    return [dict(row) for row in job.result()]


@app.get("/usuarios/{id_usuario}/extrato")
def extrato(id_usuario: str):
    query = f"""
        SELECT anomesdia, saldo_apos
        FROM `{TABELA}`
        WHERE id_usuario = @id
        ORDER BY anomesdia DESC
        LIMIT 100
    """
    job = bq.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", id_usuario)]
        ),
    )
    return [dict(row) for row in job.result()]


class Pergunta(BaseModel):
    pergunta: str = "Resuma meus gastos recentes e diga onde posso economizar."


@app.post("/usuarios/{id_usuario}/agente")
def agente(id_usuario: str, body: Pergunta):
    inicio = time.perf_counter()

    transacoes = buscar_transacoes(id_usuario)
    t_bq = time.perf_counter()

    linhas = "\n".join(
        f"{t['anomesdia']:%Y-%m-%d} | {t['tipo']} | {t['descr']} | {t['vlr']:.2f} | "
        f"{t['nom_cate_macro']}/{t['nom_cate_micro']} | saldo {t['saldo_apos']:.2f}"
        for t in transacoes
    )
    resposta = llm.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"Transações do cliente (mais recentes primeiro):\n{linhas}\n\nPergunta: {body.pergunta}",
        config=genai.types.GenerateContentConfig(system_instruction=INSTRUCOES),
    )
    fim = time.perf_counter()

    return {
        "resposta": resposta.text,
        "modelo": GEMINI_MODEL,
        "transacoes_usadas": len(transacoes),
        "latencia_ms": {
            "bigquery": round((t_bq - inicio) * 1000),
            "gemini": round((fim - t_bq) * 1000),
            "total": round((fim - inicio) * 1000),
        },
    }
