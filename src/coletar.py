#!/usr/bin/env python3
"""Snapshot do OpenSky Network para o bronze.

Roda a cada 15 minutos como Cloud Run Job e tambem pode ser executado localmente.
Com BRONZE_BUCKET, grava no GCS usando google-cloud-storage; sem a variavel,
mantem o fallback local. No Cloud Run, o bucket e a credencial OAuth2 do
OpenSky sao obrigatorios.

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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://opensky-network.org/api/states/all"
TOKEN_API = (
    "https://auth.opensky-network.org/auth/realms/"
    "opensky-network/protocol/openid-connect/token"
)

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
CREDENCIAIS_OPENSKY = os.getenv("OPENSKY_CREDENTIALS")
BRONZE_BUCKET = os.getenv("BRONZE_BUCKET")
if BRONZE_BUCKET:
    from google.cloud import storage

TIMEOUT = 30


def obter_token():
    """Obtem um token OAuth2 quando ha credenciais configuradas."""
    if not CREDENCIAIS_OPENSKY:
        return None

    credenciais = json.loads(
        pathlib.Path(CREDENCIAIS_OPENSKY).read_text(encoding="utf-8")
    )
    formulario = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": credenciais["clientId"],
            "client_secret": credenciais["clientSecret"],
        }
    ).encode("utf-8")
    requisicao = urllib.request.Request(
        TOKEN_API,
        data=formulario,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "flight-observatory/0.1",
        },
        method="POST",
    )

    with urllib.request.urlopen(requisicao, timeout=TIMEOUT) as resposta:
        resposta_token = json.load(resposta)

    return resposta_token["access_token"]


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
        "autenticacao": "oauth2" if CREDENCIAIS_OPENSKY else "anonima",
        "sucesso": None,
        "http_status": None,
        # Medido, nao suposto: e assim que se descobre o custo real em creditos
        # de uma chamada com esta bbox. Ver docs/decisoes.md.
        "quota_restante": None,
        "etapa_erro": None,
        "erro": None,
        "resposta": None,
    }

    etapa = "autenticacao"
    try:
        token = obter_token()
        cabecalhos = {"User-Agent": "flight-observatory/0.1"}
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"

        etapa = "coleta"
        req = urllib.request.Request(url, headers=cabecalhos)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            registro["http_status"] = r.status
            restante = r.headers.get("x-rate-limit-remaining")
            registro["quota_restante"] = int(restante) if restante is not None else None
            registro["resposta"] = json.load(r)
            registro["sucesso"] = True
    except urllib.error.HTTPError as e:
        registro["sucesso"] = False
        registro["http_status"] = e.code
        registro["etapa_erro"] = etapa
        registro["erro"] = f"HTTPError: {e.reason}"
        restante = e.headers.get("x-rate-limit-remaining") if e.headers else None
        registro["quota_restante"] = int(restante) if restante is not None else None
    except Exception as e:  # noqa: BLE001 — falha tambem e dado
        registro["sucesso"] = False
        registro["etapa_erro"] = etapa
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
    em_cloud_run = os.getenv("CLOUD_RUN_JOB")

    if not BRONZE_BUCKET and em_cloud_run:
        print("  ERRO: SEM bucket de bronze e esta rodando no Cloud Run", file=sys.stderr)
        return 1
    if not CREDENCIAIS_OPENSKY and em_cloud_run:
        print("  ERRO: SEM credencial OpenSky e esta rodando no Cloud Run", file=sys.stderr)
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
