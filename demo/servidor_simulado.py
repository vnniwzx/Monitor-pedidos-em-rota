"""
TMS simulado para demonstração
==============================

Servidor local que imita o comportamento de um TMS web real, com dados
100% fictícios, para rodar e testar o monitor sem acesso a sistema nenhum.

O que ele imita:
  - tela de login (qualquer usuário/senha entra);
  - painel com cards cujos números chegam via AJAX depois do carregamento
    (e o card ignora cliques enquanto mostra 0);
  - clique no card -> POST que guarda os filtros na sessão -> redireciona
    para a consulta de pedidos;
  - tabela DataTables em modo server-side, paginando de 50 em 50.

Uso:
  python demo/servidor_simulado.py            # http://127.0.0.1:8000
  python demo/servidor_simulado.py --porta 9000 --pedidos 400
"""

import argparse
import json
import os
import random
import secrets
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ------------------------------------------------------------ dados fictícios
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabi", "Heitor", "Iara",
         "João", "Karen", "Lucas", "Marina", "Nicolas", "Olívia", "Pedro", "Rafa", "Sofia"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Santos", "Lima", "Pereira", "Costa",
              "Almeida", "Ribeiro", "Martins", "Rocha", "Teixeira"]
SERVICOS = ["SHOPEE", "MERCADO ENVIO FLEX", "AVULSO"]
CLIENTES = ["LOJA EXEMPLO A", "LOJA EXEMPLO B", "LOJA EXEMPLO C"]
STATUS_MKT = (["EM ROTA DE ENTREGA"] * 4 + ["A CAMINHO (MERCADO LIVRE)"] * 2
              + ["ENTREGUE"] * 5 + ["COMPRADOR REAGENDOU", None])


def gerar_pedidos(qtd: int, seed: int = 42) -> list[dict]:
    rnd = random.Random(seed)
    hoje = date.today().isoformat()
    pedidos = []
    for i in range(qtd):
        servico = rnd.choice(SERVICOS)
        pedidos.append({
            "codigo": 100000 + i,
            "pedido": (f"BR{rnd.randint(10**11, 10**12 - 1)}" if servico == "SHOPEE"
                       else str(rnd.randint(10**10, 10**11 - 1))),
            "servico": servico,
            "cliente": rnd.choice(CLIENTES),
            "destinatario": f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}",
            "cep": f"0{rnd.randint(1000, 9999)}-{rnd.randint(0, 999):03d}",
            "status": "EM ROTA DE ENTREGA",
            "status_marketplace": rnd.choice(STATUS_MKT),
            "data": hoje,
        })
    return pedidos


# ------------------------------------------------------------ páginas
ASSETS_LOCAIS = os.environ.get("DEMO_ASSETS_DIR")  # opcional: jquery/datatables offline
if ASSETS_LOCAIS:
    JQ, DT = "/assets/jquery.min.js", "/assets/jquery.dataTables.min.js"
else:
    JQ = "https://code.jquery.com/jquery-3.7.1.min.js"
    DT = "https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"

ESTILO = """<style>
body{font-family:system-ui,Segoe UI,sans-serif;background:#f4f5f8;margin:0;padding:24px;color:#333}
.cards{display:flex;gap:12px;margin:16px 0}
.card{background:#fff;border-radius:10px;padding:14px 18px;min-width:140px;box-shadow:0 1px 3px #0002}
.card-indicador{cursor:pointer} .card span{color:#777;font-size:13px} .card h4{margin:4px 0 0;font-size:26px}
table{background:#fff;border-collapse:collapse;width:100%} th,td{padding:6px 10px;border-bottom:1px solid #eee;font-size:13px}
.aviso{background:#fff3cd;padding:8px 12px;border-radius:6px;font-size:13px}
</style>"""

LOGIN = f"""<!doctype html><html><head><meta charset=utf-8><title>Login | TMS Demo</title>{ESTILO}</head>
<body><h2>TMS Demo – Login</h2><p class=aviso>Sistema simulado. Qualquer usuário e senha entram.</p>
<form method=post action=/login><input name=usuario placeholder=Usuário> <input name=senha type=password placeholder=Senha>
<button>Acessar</button></form></body></html>"""

PAINEL = f"""<!doctype html><html><head><meta charset=utf-8><title>Painel | TMS Demo</title>{ESTILO}
<script src="{JQ}"></script></head><body>
<h2>Painel – TMS Demo</h2><p class=aviso>Dados fictícios gerados para demonstração.</p>
<div class=cards>
  <div class="card card-indicador" data-tipo="importados" data-status="1"><span>Importados</span><h4>0</h4></div>
  <div class="card card-indicador" data-tipo="emrota" data-status="6"><span>Em rota</span><h4>0</h4></div>
  <div class="card card-indicador" data-tipo="entregue" data-status="9"><span>Entregue</span><h4>0</h4></div>
</div>
<script>
// Os números chegam depois (como num painel real)
setTimeout(() => $.getJSON('/painel/dados', d => {{
  for (const [tipo, valor] of Object.entries(d)) $(`.card-indicador[data-tipo="${{tipo}}"] h4`).text(valor.toLocaleString('pt-BR'));
}}), 800);

// Card com 0 ignora o clique; senão guarda os filtros na sessão e redireciona
$(document).on('click', '.card-indicador', function () {{
  const valor = Number($(this).find('h4').text().replace(/\\./g, ''));
  if (valor === 0) return;
  $.post('/consulta/redirecionar', {{ tipo_consulta: 'cards', codstatus: String($(this).data('status')),
      dtstatus: new Date().toLocaleDateString('sv-SE') }}, r => {{ if (r.redirect) location.href = r.redirect; }}, 'json');
}});
</script></body></html>"""

PEDIDOS = f"""<!doctype html><html><head><meta charset=utf-8><title>Pedidos | TMS Demo</title>{ESTILO}
<script src="{JQ}"></script><script src="{DT}"></script></head><body>
<h2>Consulta / Pedidos</h2>
<table><thead><tr><th>Remessa</th><th>Pedido</th><th>Serviço</th><th>Destinatário</th><th>CEP</th>
<th>Status TMS</th><th>Marketplace</th></tr></thead></table>
<script>
const FILTROS = __FILTROS__;
$(function () {{
  $('table').DataTable({{
    serverSide: true, processing: true, searching: false, pageLength: 50,
    ajax: {{ url: '/consulta/pedidos/pesquisa', data: d => Object.assign(d, FILTROS) }},
    columns: ['codigo','pedido','servico','destinatario','cep','status','status_marketplace']
      .map(c => ({{ data: c, defaultContent: '' }}))
  }});
}});
</script></body></html>"""


# ------------------------------------------------------------ servidor
class TMSDemo(BaseHTTPRequestHandler):
    pedidos: list[dict] = []
    sessoes: dict[str, dict] = {}

    def log_message(self, *args):
        pass

    # helpers
    def _sessao(self):
        cookie = self.headers.get("Cookie", "")
        for parte in cookie.split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "sessao_demo" and v in self.sessoes:
                return self.sessoes[v]
        return None

    def _responder(self, corpo, tipo="text/html; charset=utf-8", status=200, extra=None):
        dados = corpo.encode() if isinstance(corpo, str) else corpo
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def _redirecionar(self, destino, extra=None):
        self._responder("", status=302, extra={"Location": destino, **(extra or {})})

    def _json(self, obj):
        self._responder(json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _corpo_form(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in parse_qs(self.rfile.read(tamanho).decode()).items()}

    # rotas
    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/assets/") and ASSETS_LOCAIS:
            arq = Path(ASSETS_LOCAIS) / Path(url.path).name
            return self._responder(arq.read_bytes(), "application/javascript")
        if url.path == "/login":
            return self._responder(LOGIN)

        sessao = self._sessao()
        if sessao is None:
            return self._redirecionar("/login")

        em_rota = [p for p in self.pedidos if p["status"] == "EM ROTA DE ENTREGA"]
        if url.path == "/":
            return self._responder(PAINEL)
        if url.path == "/painel/dados":
            return self._json({"importados": len(self.pedidos) + 37, "emrota": len(em_rota),
                               "entregue": sum(p["status_marketplace"] == "ENTREGUE" for p in em_rota)})
        if url.path == "/consulta/pedidos":
            filtros = sessao.get("filtros", {})
            return self._responder(PEDIDOS.replace("__FILTROS__", json.dumps(filtros)))
        if url.path == "/consulta/pedidos/pesquisa":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            linhas = em_rota if q.get("codstatus") == "6" else self.pedidos
            inicio, qtd = int(q.get("start", 0)), int(q.get("length", 50))
            return self._json({"draw": int(q.get("draw", 1)), "recordsTotal": len(linhas),
                               "recordsFiltered": len(linhas), "data": linhas[inicio:inicio + qtd]})
        self._responder("Não encontrado", status=404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/login":
            token = secrets.token_hex(16)
            self.sessoes[token] = {}
            return self._redirecionar("/", {"Set-Cookie": f"sessao_demo={token}; Path=/; Max-Age=2592000; HttpOnly"})
        sessao = self._sessao()
        if sessao is None:
            return self._responder("", status=401)
        if url.path == "/consulta/redirecionar":
            sessao["filtros"] = self._corpo_form()
            return self._json({"success": True, "redirect": "/consulta/pedidos"})
        self._responder("Não encontrado", status=404)


def main():
    ap = argparse.ArgumentParser(description="TMS simulado para demonstração")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--pedidos", type=int, default=250, help="quantidade de pedidos em rota")
    args = ap.parse_args()

    TMSDemo.pedidos = gerar_pedidos(args.pedidos)
    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), TMSDemo)
    print(f"TMS Demo rodando em http://127.0.0.1:{args.porta}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
