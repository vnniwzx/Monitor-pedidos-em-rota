"""
Monitor de pedidos ainda em rota
================================

Automação que confere, num TMS (sistema de gestão de transportes) web,
quais pedidos do dia continuam "em rota" no marketplace depois do horário
em que deveriam ter sido entregues, gera uma planilha e avisa a equipe.

Fluxo:
  1. Abre o TMS num navegador automatizado (Playwright) com a sessão salva.
  2. Clica no card "Em rota" do painel, como um usuário faria.
  3. Reaproveita os filtros da tabela (DataTables) para buscar todas as
     linhas de uma vez, em JSON, sem raspar a tela.
  4. Filtra os pedidos cujo status no marketplace ainda é "EM ROTA"/"A CAMINHO".
  5. Salva um CSV e notifica (Windows e, opcionalmente, Telegram).

Uso:
  python monitor_em_rota.py --login     # primeira vez: faça login no navegador que abrir
  python monitor_em_rota.py             # verificação (navegador invisível)
  python monitor_em_rota.py --visivel   # verificação mostrando o navegador

A automação é somente leitura: não altera nenhum dado no sistema.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import logging
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- caminhos
PASTA = Path(__file__).resolve().parent
PERFIL = PASTA / "perfil_navegador"      # cookies da sessão (fica fora do git)
RELATORIOS = PASTA / "relatorios"
LOGS = PASTA / "logs"
CONFIG = PASTA / "config.ini"

# Status do marketplace que ainda contam como "em rota"
STATUS_EM_ROTA = re.compile(r"EM ROTA|A CAMINHO", re.IGNORECASE)

# Colunas da planilha: (título, campo retornado pela API da tabela)
COLUNAS = [
    ("Remessa", "codigo"),
    ("Pedido", "pedido"),
    ("Serviço", "servico"),
    ("Cliente", "cliente"),
    ("Destinatário", "destinatario"),
    ("CEP", "cep"),
    ("Status TMS", "status"),
    ("Status marketplace", "status_marketplace"),
]

# Seletor do card "Em rota" no painel
SELETOR_CARD = '.card-indicador[data-tipo="emrota"]'

# JavaScript executado dentro da página de pedidos.
# A tabela usa DataTables em modo server-side (pagina de 50 em 50).
# Reaproveitamos os mesmos filtros que o card aplicou e pedimos tudo de uma vez.
JS_TABELA_PRONTA = """
() => {
  try {
    if (!window.$ || !$.fn.dataTable || !$.fn.dataTable.isDataTable('table')) return false;
    const dt = $('table').DataTable();
    return !!(dt.ajax.params() && dt.settings()[0].json);
  } catch (e) { return false; }
}
"""

JS_BUSCAR_TODOS = """
async () => {
  const dt = $('table').DataTable();
  const p = JSON.parse(JSON.stringify(dt.ajax.params()));
  p.start = 0;
  p.length = 5000;
  p.draw = 99;
  const r = await $.ajax({ url: dt.ajax.url(), data: p, type: 'GET' });
  return {
    filtros: { codstatus: p.codstatus, dtstatus: p.dtstatus, tipo_consulta: p.tipo_consulta },
    total: r.recordsFiltered,
    linhas: r.data,
  };
}
"""


class LoginExpirado(Exception):
    """A sessão salva expirou e o sistema redirecionou para o login."""


# ================================================================ regras
# Funções puras (sem navegador) — cobertas pelos testes em tests/.

def filtrar_pendentes(linhas: list[dict]) -> list[dict]:
    """Mantém só os pedidos que ainda estão em rota no marketplace."""
    return [p for p in linhas if STATUS_EM_ROTA.search(p.get("status_marketplace") or "")]


def montar_resumo(pendentes: list[dict], total_em_rota: int, agora: datetime,
                  limite_lista: int = 30) -> str:
    """Texto curto para notificação / Telegram (sem nome de destinatário)."""
    hora = f"{agora:%H:%M}"
    if not pendentes:
        return f"✅ {hora} – Nenhum pedido ainda em rota (de {total_em_rota} em rota no TMS)."

    por_status = Counter(p.get("status_marketplace") for p in pendentes)
    por_servico = Counter(p.get("servico") for p in pendentes)
    linhas = [
        f"🚚 {hora} – {len(pendentes)} pedidos ainda em rota "
        f"(de {total_em_rota} em rota no TMS)",
        "",
        " | ".join(f"{k}: {v}" for k, v in por_status.most_common()),
        " | ".join(f"{k}: {v}" for k, v in por_servico.most_common()),
        "",
    ]
    for p in pendentes[:limite_lista]:
        linhas.append(f"{p.get('codigo')} · {p.get('pedido')} · "
                      f"CEP {p.get('cep')} · {p.get('status_marketplace')}")
    if len(pendentes) > limite_lista:
        linhas.append(f"... e mais {len(pendentes) - limite_lista} (veja a planilha)")
    return "\n".join(linhas)


def salvar_csv(pendentes: list[dict], agora: datetime, pasta: Path = RELATORIOS) -> Path:
    """CSV com ';' e UTF-8 com BOM: abre direto no Excel em português."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"pedidos-em-rota-{agora:%Y-%m-%d-%Hh%M}.csv"
    with open(arquivo, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([titulo for titulo, _ in COLUNAS])
        for p in pendentes:
            w.writerow([p.get(campo) or "" for _, campo in COLUNAS])
    return arquivo


def ler_sim_nao(valor: str) -> bool:
    return valor.strip().lower() in ("sim", "s", "yes", "y", "true", "1")


# ================================================================ infraestrutura
def configurar_log() -> None:
    LOGS.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOGS / "verificacoes.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def carregar_config() -> dict:
    if not CONFIG.exists():
        sys.exit("config.ini não encontrado. Copie o config.exemplo.ini para config.ini e preencha.")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")
    return {
        "url": cfg.get("sistema", "url").rstrip("/"),
        "tg_token": cfg.get("telegram", "token", fallback="").strip(),
        "tg_chat": cfg.get("telegram", "chat_id", fallback="").strip(),
        "tg_planilha": ler_sim_nao(cfg.get("telegram", "enviar_planilha", fallback="nao")),
    }


def notificar_windows(titulo: str, mensagem: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=titulo[:63], message=mensagem[:250],
                            app_name="Monitor Em Rota", timeout=15)
    except Exception as e:  # notificação é "bônus": nunca derruba a verificação
        logging.warning("Notificação indisponível: %s", e)


def enviar_telegram(cfg: dict, texto: str, arquivo: Path | None = None) -> None:
    if not (cfg["tg_token"] and cfg["tg_chat"]):
        return
    import requests
    base = f"https://api.telegram.org/bot{cfg['tg_token']}"
    try:
        requests.post(f"{base}/sendMessage",
                      data={"chat_id": cfg["tg_chat"], "text": texto[:4000]},
                      timeout=30).raise_for_status()
        if arquivo and cfg["tg_planilha"]:
            with open(arquivo, "rb") as f:
                requests.post(f"{base}/sendDocument", data={"chat_id": cfg["tg_chat"]},
                              files={"document": (arquivo.name, f)},
                              timeout=60).raise_for_status()
    except Exception as e:
        logging.warning("Falha ao enviar para o Telegram: %s", e)


# ================================================================ navegador
def abrir_navegador(p, visivel: bool):
    PERFIL.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PERFIL),
        headless=not visivel,
        viewport={"width": 1400, "height": 900},
        locale="pt-BR",
    )


def modo_login(cfg: dict) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = abrir_navegador(p, visivel=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["url"] + "/")
        print("\n>>> Faça login na janela que abriu. Quando o painel aparecer, ela fecha sozinha.\n")
        page.wait_for_url(lambda u: "/login" not in u, timeout=0)
        page.wait_for_load_state("networkidle")
        print("Login salvo! Agora rode a verificação (testar.bat ou sem --login).")
        ctx.close()


def numero_do_card(card) -> int:
    digitos = re.sub(r"\D", "", card.locator("h4, h3").first.inner_text())
    return int(digitos) if digitos else 0


def buscar_pedidos(cfg: dict, visivel: bool) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = abrir_navegador(p, visivel)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            logging.info("Abrindo o painel...")
            page.goto(cfg["url"] + "/", wait_until="domcontentloaded", timeout=60_000)
            if "/login" in page.url:
                raise LoginExpirado()

            card = page.locator(SELETOR_CARD)
            card.wait_for(state="visible", timeout=30_000)

            # Os números dos cards chegam via AJAX depois do carregamento.
            # Clicar enquanto o card mostra 0 não faz nada, então esperamos.
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            em_rota = numero_do_card(card)
            for _ in range(20):
                if em_rota > 0:
                    break
                page.wait_for_timeout(500)
                em_rota = numero_do_card(card)
            logging.info("Card 'Em rota' mostra %d pedidos.", em_rota)
            if em_rota == 0:
                return {"filtros": {}, "total": 0, "linhas": []}

            logging.info("Clicando no card 'Em rota'...")
            card.click()
            page.wait_for_url("**/consulta/pedidos**", timeout=30_000)
            logging.info("Carregando a lista de pedidos...")
            page.wait_for_function(JS_TABELA_PRONTA, timeout=30_000)
            return page.evaluate(JS_BUSCAR_TODOS)
        except LoginExpirado:
            raise
        except Exception:
            try:
                LOGS.mkdir(exist_ok=True)
                foto = LOGS / f"erro-{datetime.now():%Y-%m-%d-%Hh%Mm%S}.png"
                page.screenshot(path=str(foto), full_page=True)
                logging.error("Print da tela no momento do erro: %s", foto)
            except Exception:
                pass
            raise
        finally:
            ctx.close()


# ================================================================ principal
def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica pedidos ainda em rota no TMS.")
    parser.add_argument("--login", action="store_true", help="abre o navegador para fazer login")
    parser.add_argument("--visivel", action="store_true", help="mostra o navegador durante a verificação")
    args = parser.parse_args()

    configurar_log()
    cfg = carregar_config()

    if args.login:
        modo_login(cfg)
        return 0

    agora = datetime.now()
    try:
        resultado = buscar_pedidos(cfg, args.visivel)
    except LoginExpirado:
        msg = "A sessão expirou. Rode o fazer_login.bat e entre de novo."
        logging.error(msg)
        notificar_windows("Monitor Em Rota: login expirado", msg)
        enviar_telegram(cfg, "⚠️ " + msg)
        return 2
    except Exception as e:
        logging.exception("Erro na verificação")
        notificar_windows("Monitor Em Rota: erro", str(e))
        enviar_telegram(cfg, f"❌ Erro na verificação: {e}")
        return 1

    linhas = resultado["linhas"]
    logging.info("Filtros: %s | linhas recebidas: %d de %s",
                 resultado["filtros"], len(linhas), resultado["total"])
    if resultado["total"] and len(linhas) < int(resultado["total"]):
        logging.warning("Vieram menos linhas (%d) do que o total (%s).", len(linhas), resultado["total"])

    pendentes = filtrar_pendentes(linhas)
    arquivo = salvar_csv(pendentes, agora)
    resumo = montar_resumo(pendentes, len(linhas), agora)

    logging.info("Resultado: %d ainda em rota. Planilha: %s", len(pendentes), arquivo)
    print("\n" + resumo + "\n")
    notificar_windows(f"{len(pendentes)} pedidos ainda em rota",
                      f"Planilha salva em relatorios\\{arquivo.name}")
    enviar_telegram(cfg, resumo, arquivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
