"""Resume um JTL sem publicar corpos, credenciais ou identificadores pessoais."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def percentil(valores, proporcao):
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(len(ordenados) * proporcao) - 1)]


def resumo(amostras):
    tempos = [int(a["elapsed"]) for a in amostras]
    falhas = sum(a["success"] != "true" for a in amostras)
    return {
        "requisicoes": len(amostras),
        "falhas": falhas,
        "erro_percentual": round(100 * falhas / len(amostras), 4),
        "mediana_ms": percentil(tempos, 0.5),
        "p95_ms": percentil(tempos, 0.95),
        "maximo_ms": max(tempos),
    }


def analisar(arquivo, inicio, duracao, usuarios):
    with arquivo.open() as entrada:
        linhas = list(csv.DictReader(entrada))
    if not linhas or any(a["success"] not in {"true", "false"} for a in linhas):
        raise ValueError("JTL vazio ou incompleto; aguarde o encerramento do JMeter.")
    marco = min(int(a["timeStamp"]) for a in linhas)
    fim = marco + (inicio + duracao) * 1000
    completo = max(int(a["timeStamp"]) + int(a["elapsed"]) for a in linhas) >= fim
    http = [a for a in linhas if a["label"] != "Preparar pessoa sintética"]
    janela = [a for a in http if marco + inicio * 1000 <= int(a["timeStamp"]) < fim]
    if not janela:
        raise ValueError("A janela escolhida não contém requisições HTTP.")
    grupos = defaultdict(list)
    for amostra in janela:
        grupos[amostra["label"]].append(amostra)
    rotas = {nome: resumo(grupo) for nome, grupo in sorted(grupos.items())}
    threads = [int(a["allThreads"]) for a in janela]
    total = resumo(janela)
    esperado = {
        "Perfil",
        "Planejamento",
        "Avulsas",
        "Jornada",
        "Diário",
        "Loja",
        "Progresso semana",
        "Progresso mês",
        "Progresso seis meses",
        "Referências",
        "Semana salva",
        "Histórico missões",
        "Extrato",
        "Criar missão",
        "Concluir missão",
        "Resgatar",
        "Estornar",
        "Isolamento esperado 404",
    }
    criterios = {
        "dez_minutos_completos": completo and duracao >= 600,
        "usuarios_simultaneos": min(threads) == max(threads) == usuarios,
        "todas_operacoes_presentes": esperado.issubset(grupos),
        "p95_por_operacao_ate_2s": all(r["p95_ms"] <= 2000 for r in rotas.values()),
        "erro_menor_que_1_porcento": total["erro_percentual"] < 1,
    }
    return {
        "janela": {
            "inicio_segundos": inicio,
            "duracao_segundos": duracao,
            "completa": completo,
            "usuarios_minimos": min(threads),
            "usuarios_maximos": max(threads),
        },
        "http_total_ensaio": resumo(http),
        "http_janela": total,
        "rotas": rotas,
        "criterios_cenario_local": criterios,
        "atende_cenario_local": all(criterios.values()),
        "observacao": "Isolamento espera 404; IA externa e ETL não integram este ensaio.",
    }


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("jtl", type=Path)
    argumentos.add_argument("--inicio", type=int, default=45)
    argumentos.add_argument("--duracao", type=int, default=600)
    argumentos.add_argument("--usuarios", type=int, default=50)
    argumentos.add_argument("--saida", type=Path)
    opcoes = argumentos.parse_args()
    resultado = analisar(opcoes.jtl, opcoes.inicio, opcoes.duracao, opcoes.usuarios)
    conteudo = json.dumps(resultado, indent=2, ensure_ascii=False) + "\n"
    if opcoes.saida:
        opcoes.saida.write_text(conteudo)
    print(conteudo, end="")
