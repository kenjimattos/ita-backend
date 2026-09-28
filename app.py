import os
import time

from fastapi import FastAPI
from google import genai

app = FastAPI()

# gemini-3.x só está disponível na location "global" do Vertex AI
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
llm = genai.Client(vertexai=True, project=os.environ.get("PROJ"))

INSTRUCOES = """Responda em português brasileiro, de forma curta e direta."""


@app.post("/agente")
def agente():
    inicio = time.perf_counter()

    pergunta: str = "Como funcionam as IAs?"

    resposta = llm.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{pergunta}",
        config=genai.types.GenerateContentConfig(system_instruction=INSTRUCOES),
    )
    fim = time.perf_counter()

    return {
        "resposta": resposta.text,
        "latencia_ms": {"gemini": round((fim - inicio) * 1000)},
    }
