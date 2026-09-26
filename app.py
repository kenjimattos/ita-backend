import os

from fastapi import FastAPI
from google.cloud import bigquery

app = FastAPI()
bq = bigquery.Client()

TABELA = os.environ["TABLE_NAME"]


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
