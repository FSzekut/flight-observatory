# Decisões de projeto

## 2026-09-14 — só o OpenSky é coletado desde o dia 1, e o motivo é assimetria

O projeto usa três fontes, e só uma é irrecuperável:

| Fonte | Recuperável depois? |
|---|---|
| **OpenSky** | ❌ **não.** Posição ao vivo. Passou o instante, acabou |
| Open-Meteo | ✅ sim. A API de arquivo devolve hora a hora do passado — verificado em 14/09, 72 horas de agosto com visibilidade, temperatura e vento |
| Aviation Safety Data | ✅ sim. As 164.271 narrativas são históricas e estáticas |

**Consequência: o coletor do dia 1 é só o OpenSky.** Meteorologia e narrativas entram na
semana 2 sem perder um único dia de série. Gastar a primeira noite montando as três teria
custado dias de denominador por nada.

## 2026-09-14 — cadência de 15 minutos, e o custo em créditos foi medido

O acesso anônimo do OpenSky tem **400 créditos por dia**. O custo por chamada depende da área
da *bounding box*, e em vez de deduzir da documentação **o coletor mede**: ele grava
`x-rate-limit-remaining` em todo registro de bronze.

**Medição de 14/09:**

| Bounding box | Área | Custo observado |
|---|---|---|
| Curitiba, 1° × 2° | 2 graus² | **1 crédito** |
| Sudeste, 5° × 6,5° | 32,5 graus² | **2 créditos** |

**A 15 minutos: 96 chamadas por dia × 2 = 192 créditos.** Sobram mais de 200 para reprocessar,
testar e cobrir falha.

🎯 **Por que 15 minutos e não de hora em hora:** reduzir resolução depois é trivial, aumentar é
impossível. É o mesmo princípio do bronze guardar o cru, aplicado ao tempo em vez de ao campo.

## 2026-09-14 — cron direto, e não um job que dorme

A alternativa era uma execução por hora tirando quatro snapshots com `sleep` entre eles, para
contornar o atraso do agendador do GitHub.

**Descartada.** O jitter não atrapalha, porque **cada snapshot grava o próprio timestamp** — o
que se constrói é amostra de exposição, não grade regular. E o job dormindo consumiria cerca de
**18 horas de runner por dia**, o que só é gratuito em repositório público e desperdiça mesmo
quando é.

## 2026-09-14 — o bronze é versionado no git

Contraria a regra geral da máquina, que manda saída gerada ir para `outputs/` fora do git. A
exceção é a mesma do `job-observatory`: **aqui o bronze não é saída gerada, é o dado de
origem** — e ele não existe em nenhum outro lugar depois que o instante passa.

São alguns KB por snapshot. `outputs/` continua no `.gitignore`.

## 2026-09-14 — a região é o corredor Sudeste

`lat -24,5 a -19,5` por `lon -48,5 a -42,0`, cobrindo as áreas terminais de São Paulo, Rio de
Janeiro e Belo Horizonte. É onde está o maior tráfego do país, então é onde a amostra de
exposição rende mais por crédito gasto.

**Primeira coleta real: 78 aeronaves.** A região é configurável por variável de ambiente
(`LAMIN`, `LOMIN`, `LAMAX`, `LOMAX`, `REGIAO`), então acrescentar uma segunda é mudar o
workflow, não o código.

## 2026-09-14 — falha é gravada, não engolida

Chamada que falha **grava o registro de falha no bronze** com o erro e o horário, e o workflow
**não quebra**. Buraco declarado vale mais que buraco silencioso: na hora de calcular taxa, é
preciso saber a diferença entre "não havia aeronave" e "não houve coleta".
