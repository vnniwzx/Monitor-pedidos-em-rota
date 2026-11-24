import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor_em_rota import filtrar_pendentes, ler_sim_nao, montar_resumo, salvar_csv  # noqa: E402

AGORA = datetime(2026, 11, 24, 21, 2)


def pedido(codigo, status_mkt, servico="SHOPEE"):
    return {"codigo": codigo, "pedido": f"BR{codigo}", "servico": servico, "cliente": "LOJA",
            "destinatario": "Fulano", "cep": "01000-000", "status": "EM ROTA DE ENTREGA",
            "status_marketplace": status_mkt}


def test_filtra_em_rota_e_a_caminho():
    linhas = [pedido(1, "EM ROTA DE ENTREGA"), pedido(2, "A CAMINHO (MERCADO LIVRE)"),
              pedido(3, "ENTREGUE"), pedido(4, None), pedido(5, "COMPRADOR REAGENDOU")]
    assert [p["codigo"] for p in filtrar_pendentes(linhas)] == [1, 2]


def test_resumo_sem_pendentes():
    assert montar_resumo([], 10, AGORA).startswith("✅ 21:02 – Nenhum pedido")


def test_resumo_lista_limitada_e_sem_nome_de_cliente():
    pendentes = [pedido(i, "EM ROTA DE ENTREGA") for i in range(35)]
    texto = montar_resumo(pendentes, 50, AGORA, limite_lista=30)
    assert texto.startswith("🚚 21:02 – 35 pedidos ainda em rota (de 50 em rota no TMS)")
    assert "... e mais 5" in texto
    assert "Fulano" not in texto  # dado pessoal fica só na planilha


def test_csv_abre_no_excel(tmp_path):
    arquivo = salvar_csv([pedido(1, "EM ROTA DE ENTREGA")], AGORA, pasta=tmp_path)
    assert arquivo.name == "pedidos-em-rota-2026-11-24-21h02.csv"
    assert arquivo.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM para o Excel
    with open(arquivo, encoding="utf-8-sig") as f:
        linhas = list(csv.reader(f, delimiter=";"))
    assert linhas[0][0] == "Remessa" and linhas[1][0] == "1"


def test_sim_nao_em_portugues():
    assert ler_sim_nao("sim") and ler_sim_nao(" SIM ")
    assert not ler_sim_nao("nao") and not ler_sim_nao("")
