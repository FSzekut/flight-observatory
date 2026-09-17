#!/usr/bin/env python3
"""Snapshot do OpenSky Network para o bronze.

Roda a cada 15 minutos como Cloud Run Job e tambem pode ser executado localmente.
Com BRONZE_BUCKET, grava no GCS usando google-cloud-storage; sem a variavel,
mantem o fallback local. No Cloud Run, o bucket e obrigatorio.

O QUE ESTE ARQUIVO NAO FAZ, e isso e regra:
nao deduplica, nao filtra, nao normaliza e nao descarta campo. Bronze guarda o
retorno cru mais o metadado da coleta. Se a regra de limpeza mudar amanha, da
para reprocessar; o que for descartado aqui nao volta nunca.

O OpenSky e a UNICA das tres fontes do projeto que e irrecuperavel. Meteorologia
tem API de arquivo e as narrativas de acidente sao historicas. Por isso ele e o
unico coletor que existe desde o dia 1.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://opensky-network.org/api/states/all"

# Corredor Sudeste: a regiao de maior trafego do pais, cobrindo a area
# terminal de Sao Paulo, Rio e Belo Horizonte. Ver docs/decisoes.md.
BBOX = {
    "lamin": float(os.getenv("LAMIN", "-24.5")),
    "lomin": float(os.getenv("LOMIN", "-48.5")),
    "lamax": float(os.getenv("LAMAX", "-19.5")),
    "lomax": float(os.getenv("LOMAX", "-42.0")),
}
REGIAO = os.getenv("REGIAO", "sudeste")
RAIZ = pathlib.Path(__file__).resolve().parent.parent
BRONZE = RAIZ / "data" / "bronze"
BRONZE_BUCKET = os.getenv("BRONZE_BUCKET")
if BRONZE_BUCKET:
    from google.cloud import storage

TIMEOUT = 30


def coletar():
    """Uma chamada. Devolve o registro de bronze, tenha dado certo ou nao."""
    agora = datetime.now(timezone.utc)
    qs = "&".join(f"{k}={v}" for k, v in BBOX.items())
    url = f"{API}?{qs}"

    registro = {
        "coletado_em": agora.isoformat(),
        "regiao": REGIAO,
        "bbox": BBOX,
        "url": url,
        "fonte": "opensky-network",
        "sucesso": None,
        "http_status": None,
        # Medido, nao suposto: e assim que se descobre o custo real em creditos
        # de uma chamada com esta bbox. Ver docs/decisoes.md.
        "quota_restante": None,
        "erro": None,
        "resposta": None,
    }

    req = urllib.request.Request(url, headers={"User-Agent": "flight-observatory/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            registro["http_status"] = r.status
            restante = r.headers.get("x-rate-limit-remaining")
            registro["quota_restante"] = int(restante) if restante is not None else None
            registro["resposta"] = json.load(r)
            registro["sucesso"] = True
    except urllib.error.HTTPError as e:
        registro["sucesso"] = False
        registro["http_status"] = e.code
        registro["erro"] = f"HTTPError: {e.reason}"
        restante = e.headers.get("x-rate-limit-remaining") if e.headers else None
        registro["quota_restante"] = int(restante) if restante is not None else None
    except Exception as e:  # noqa: BLE001 — falha tambem e dado
        registro["sucesso"] = False
        registro["erro"] = f"{type(e).__name__}: {e}"

    return agora, registro


def gravar(agora, registro):
    """Grava o snapshot no GCS ou localmente."""

    nome_arquivo = f"opensky-{REGIAO}-{agora:%H%M%S}.json"

    # Serializa exatamente uma vez.
    conteudo = json.dumps(
        registro,
        ensure_ascii=False,
    )

    if BRONZE_BUCKET:
        # Isto e um nome de objeto GCS, nao um caminho local.
        nome_objeto = (
            f"bronze/"
            f"coleta_date={agora:%Y-%m-%d}/"
            f"{nome_arquivo}"
        )
        try:
            cliente = storage.Client()
            bucket = cliente.bucket(BRONZE_BUCKET)
            blob = bucket.blob(nome_objeto)

            blob.upload_from_string(
                conteudo,
                content_type="application/json",
            )
        except Exception as erro:
            falha = {
                "tipo": "falha_persistencia",
                "destino": f"gs://{BRONZE_BUCKET}/{nome_objeto}",
                "erro": f"{type(erro).__name__}: {erro}",
                "registro": registro,
            }
            json.dump(falha, sys.stderr, ensure_ascii=False)
            print(file=sys.stderr)
            raise
        return f"gs://{BRONZE_BUCKET}/{nome_objeto}"

    # Armazenamento local.
    parte = BRONZE / f"coleta_date={agora:%Y-%m-%d}"
    parte.mkdir(parents=True, exist_ok=True)

    destino = parte / nome_arquivo

    destino.write_text(
        conteudo,
        encoding="utf-8",
    )

    return str(destino.relative_to(RAIZ))


def main():
    if not BRONZE_BUCKET and os.getenv("CLOUD_RUN_JOB"):
        print("  ERRO: SEM bucket de bronze e esta rodando no Cloud Run", file=sys.stderr)
        return 1

    agora, registro = coletar()
    destino = gravar(agora, registro)

    n = len((registro.get("resposta") or {}).get("states") or [])
    quota = registro["quota_restante"]
    print(f"  gravado em: {destino}")
    print(f"  sucesso: {registro['sucesso']} | http: {registro['http_status']}")
    print(f"  aeronaves: {n}")
    print(f"  quota restante: {quota}")

    # Falha nao derruba o workflow: o registro de falha JA foi gravado, e um
    # buraco declarado vale mais que um buraco silencioso. Mas avisa alto.
    if not registro["sucesso"]:
        print(f"  ATENCAO falhou: {registro['erro']}", file=sys.stderr)
    if quota is not None and quota < 50:
        print(f"  ATENCAO quota baixa: {quota}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
