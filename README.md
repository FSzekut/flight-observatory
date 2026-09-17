# Flight Observatory

Série temporal de voos e condições meteorológicas, coletada a cada 15 minutos, para servir de
**denominador** à análise de ocorrências aéreas.

![passo](https://img.shields.io/badge/passo-0%20bronze-blue) ![python](https://img.shields.io/badge/python-3.12-informational) ![licen%C3%A7a](https://img.shields.io/badge/licen%C3%A7a-MIT-green)

**Estado: passo 0 (bronze).** Coleta validada contra o GCS; migração do agendamento para
Cloud Run e Cloud Scheduler em andamento.

## Por que existe

Existem **164.271 narrativas de acidente aéreo** agregadas de **130 fontes oficiais** — NTSB,
ATSB, MAK e agências nacionais de investigação. É um corpus público, denso e bem mantido.

🎯 **E ele é só numerador.** Registra o que deu errado e não registra o que deu certo nas mesmas
condições.

Por isso toda análise sobre essas bases chega à mesma banalidade: *acidente acontece com tempo
ruim*. Só que um milhão de voos seguros também aconteceu com tempo ruim, no mesmo período, nos
mesmos aeroportos. **Sem denominador não existe taxa, existe correlação.**

Este repositório constrói o denominador que falta: quantas aeronaves estavam no ar, onde, e sob
quais condições — amostrado a cada 15 minutos, indefinidamente.

**O dado precisa ser guardado porque ele não é recuperável.** A posição de uma aeronave às
19h08 de hoje não existe em lugar nenhum às 19h09. Meteorologia tem API de arquivo e as
narrativas são históricas; só o voo ao vivo é irreversível. É por isso que ele é o único
coletor que existe desde o dia 1.

## Arquitetura

```
OpenSky (15 min) ──► Cloud Run Job ──► GCS bronze ──► silver ──► gold
  Open-Meteo                                      cru     limpo e    taxa
  Aviation Safety                                         normalizado

gold ──► agente com RAG ──► servidor MCP
          cita a narrativa
          de origem
```

## O princípio do bronze, e ele não se negocia

**Bronze guarda o retorno cru, sem transformação.** Sem dedup, sem filtro, sem normalização. O
que se acrescenta é só metadado de coleta: quando, com qual bounding box, com qual quota
restante, e se deu certo.

Se a regra de limpeza mudar amanhã, dá para reprocessar tudo. Se a limpeza acontecer no bronze,
o que foi descartado não volta nunca.

**Falha também é dado.** Chamada ao OpenSky que falha grava o registro de falha, e o job não
quebra. Falha de persistência é diferente: o snapshot original vai para o log estruturado e o
job termina com erro. Na hora de calcular taxa é preciso distinguir *"não havia aeronave"* de
*"não houve coleta"*.

## Estrutura

```
src/coletar.py                       coleta e grava no GCS ou no fallback local
requirements.txt                    dependência do cliente GCS
.github/workflows/coletar.yml        coletor legado durante a transição
data/bronze/coleta_date=YYYY-MM-DD/  fallback local e histórico já coletado
docs/decisoes.md                     por que cada escolha foi feita
```

## Cota, e ela foi medida

O acesso anônimo do OpenSky tem **400 créditos por dia**, e o custo por chamada depende da área
da bounding box. Em vez de deduzir da documentação, **o coletor mede**: grava
`x-rate-limit-remaining` em todo registro.

| Bounding box | Área | Custo medido |
|---|---|---|
| Curitiba, 1° × 2° | 2 graus² | 1 crédito |
| **Sudeste, 5° × 6,5°** | 32,5 graus² | **2 créditos** |

**A 15 minutos: 96 chamadas × 2 = 192 créditos por dia.** Sobram mais de 200 para reprocessar,
testar e cobrir falha.

## Uso

Crie o ambiente e instale a dependência:

```bash
uv venv
uv pip install -r requirements.txt
```

Sem `BRONZE_BUCKET`, o coletor preserva o comportamento local:

```bash
.venv/bin/python src/coletar.py
```

Com `BRONZE_BUCKET`, grava o mesmo JSON no GCS e mantém o caminho de partição Hive-style:

```bash
BRONZE_BUCKET=fszekut-flight-observatory-bronze .venv/bin/python src/coletar.py
```

Localmente, o cliente GCS usa Application Default Credentials. No Cloud Run, usa a identidade
do serviço, sem arquivo de chave. Se `CLOUD_RUN_JOB` existir e `BRONZE_BUCKET` estiver ausente,
o processo falha antes de consumir quota do OpenSky.

A região continua configurável por ambiente:

```bash
LAMIN=-26 LOMIN=-50 LAMAX=-25 LOMAX=-48 REGIAO=curitiba \
  .venv/bin/python src/coletar.py
```

## Sobre os dados

Posições de aeronave transmitidas publicamente por **ADS-B** e agregadas pela OpenSky Network,
e dados meteorológicos públicos. **Nenhum dado pessoal é coletado, armazenado ou processado.**

## 🛑 O que este projeto não faz

**Não prevê acidente, e isso é decisão de arquitetura.** Segurança aérea é disciplina regulada e
madura, com dados e métodos que este repositório não tem.

O sistema **descreve**: *estas condições aparecem em N narrativas históricas, e há M aeronaves
operando em condição semelhante*. Ele **não** diz que um voo está em risco, e a camada de
guardrail existe para impedir que ele diga.

## Passos

| Passo | Estado |
|---|---|
| 0. Bronze — coleta do OpenSky | 🔵 em andamento |
| 1. Meteorologia (Open-Meteo, inclusive retroativa) | a fazer |
| 2. Narrativas (Aviation Safety Data) | a fazer |
| 3. Silver e gold, com o denominador | a fazer |
| 4. RAG sobre as narrativas, com citação por registro | a fazer |
| 5. Camada de avaliação e guardrail anti-previsão | a fazer |
| 6. Servidor MCP e frente ao vivo | a fazer |

## Licença

MIT. Ver [LICENSE](LICENSE).
