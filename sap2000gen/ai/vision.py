"""IA de vision (API OpenAI-compatible) para interpretar planos.

Configuracion via variables de entorno / .env:
    OPENAI_API_KEY  - clave de API (OpenAI, Azure, OpenRouter, Ollama...)
    OPENAI_BASE_URL - url base (opcional; default https://api.openai.com/v1)
    VISION_MODEL    - modelo multimodal (default gpt-4o-mini)

La funcion `interpret_plan` envia la imagen del plano y devuelve un JSON
estructurado con nudos, barras, secciones y cargas, listo para alimentar
el generador .s2k.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Dict, Optional

try:
    from openai import OpenAI
    OPENAI_OK = True
except Exception:  # pragma: no cover
    OPENAI_OK = False

from dotenv import load_dotenv

SYSTEM_PROMPT = """Eres un ingeniero estructural experto en SAP2000. Recibes una imagen de un plano
estructural (planta o elevacion de estructura metalica). Debes extraer la geometria
y devolver SOLO un JSON valido, sin texto adicional, con esta estructura:

{
  "units": "m",
  "notes": "breve descripcion de lo que ves",
  "joints": [{"id": 1, "x": 0.0, "y": 0.0, "z": 6.0}, ...],
  "frames": [{"i": 1, "j": 2, "section": "ARCO"}, ...],
  "sections": [{"name": "ARCO", "material": "A36", "shape": "General", "area": 0.004555}],
  "supports": [{"joint": 1, "restraints": [true,true,true,true,true,true]}],
  "joint_loads": [{"joint": 2, "pattern": "CM", "f3": -3.0}]
}

Reglas:
- Trabaja en metros. Usa las cotas y escalas del plano.
- Los nudos deben estar en la interseccion de las barras (un solo nudo compartido).
- Las secciones son nombres como ARCO, COL, CORD150, DIAG100, CSA5_8; si el plano
  no las define usa "ARCO".
- Si la imagen no es un plano estructural, devuelve {\"error\": \"descripcion\"}.
"""


def _load_env() -> None:
    # busca .env en el directorio del paquete o en el cwd
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]
    for c in candidates:
        if os.path.exists(c):
            load_dotenv(c)
            return


def _client() -> OpenAI:
    if not OPENAI_OK:
        raise RuntimeError("Falta openai: pip install openai")
    _load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta OPENAI_API_KEY. Configurala en variables de entorno o en un archivo .env "
            "(ej: OPENAI_API_KEY=sk-... VISION_MODEL=gpt-4o-mini OPENAI_BASE_URL=...)")
    kwargs: Dict = {"api_key": api_key}
    if os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    return OpenAI(**kwargs)


def _image_b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def _extract_json(text: str) -> dict:
    """Extrae y parsea un JSON de la respuesta del modelo de forma robusta."""
    import json as _json

    # 1) quitar fences de markdown
    text = re.sub(r"```(?:json)?", "", text)
    text = text.replace("```", "")

    # 2) buscar el bloque balanceado { ... } mas grande
    def find_balanced(s: str, start: int) -> str | None:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        return None

    start = text.find("{")
    while start != -1:
        candidate = find_balanced(text, start)
        if candidate:
            try:
                return _json.loads(candidate)
            except _json.JSONDecodeError:
                # 3) reintentar quitando comas finales (trailing commas)
                cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return _json.loads(cleaned)
                except _json.JSONDecodeError:
                    pass
        start = text.find("{", start + 1)

    raise ValueError(f"No se encontro JSON en la respuesta del modelo: {text[:500]}")


def interpret_plan(image_path: str, extra_context: Optional[str] = None,
                   model: Optional[str] = None) -> dict:
    """Envia la imagen del plano a la IA de vision y devuelve el JSON de geometria."""
    client = _client()
    _load_env()
    model = model or os.environ.get("VISION_MODEL", "gpt-4o-mini")

    prompt = SYSTEM_PROMPT
    if extra_context:
        prompt += f"\n\nContexto adicional del plano (extraido por OCR/DXF):\n{extra_context}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{_image_b64(image_path)}"}},
            ]},
        ],
        temperature=0.0,
        max_tokens=6000,
    )
    content = resp.choices[0].message.content
    result = _extract_json(content)
    if "error" in result:
        raise ValueError(f"El modelo no identifico un plano estructural: {result['error']}")
    return result
