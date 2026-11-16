# ui_server.py
# Servidor da "sala da squad".
#   - Serve a pagina ui/index.html
#   - Expoe o estado atual dos agentes em /status (JSON)
#
# Padroes usados:
#   - Observer: o main.py PUBLICA eventos na SalaStatus; a pagina OBSERVA
#     consultando /status a cada ~1s. O CrewAI nao sabe que a sala existe.
#   - Decorator: observar_guardrail() envolve um guardrail existente para
#     avisar a sala quando ele reprova, sem alterar o guardrails.py.

import json
import threading
import time
import uuid
import webbrowser
from functools import wraps
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PASTA_UI = Path(__file__).parent / "ui"
MAX_EVENTOS = 100


class SalaStatus:
    """Estado compartilhado entre o CrewAI (thread principal) e o servidor (outra thread)."""

    def __init__(self):
        self._trava = threading.Lock()
        self._proximo_id = 1
        self._dados = {
            "sessao": uuid.uuid4().hex[:8],  # muda a cada execucao: a pagina limpa o diario
            "estado": "aguardando",          # aguardando | pensando | escrevendo | revisando | pronto | erro
            "etapa": None,                   # None | descoberta | backlog | fim
            "ideia": "",
            "tentativa": 0,                  # reprovacoes do guardrail na etapa atual
            "motivo": "",                    # ultima mensagem de erro do guardrail
            "eventos": [],
        }

    def publicar(self, mensagem, tipo="info", **campos):
        """Atualiza campos do estado e registra um evento no diario da sala."""
        with self._trava:
            self._dados.update(campos)
            self._dados["eventos"].append({
                "id": self._proximo_id,
                "hora": time.strftime("%H:%M:%S"),
                "texto": mensagem,
                "tipo": tipo,  # info | ok | alerta | erro
            })
            self._proximo_id += 1
            del self._dados["eventos"][:-MAX_EVENTOS]

    def registrar_falha(self, motivo):
        tentativa = self.get("tentativa") + 1
        self.publicar(
            f"Guardrail reprovou (tentativa {tentativa}): {motivo}",
            tipo="alerta",
            estado="revisando",
            tentativa=tentativa,
            motivo=motivo,
        )

    def get(self, campo):
        with self._trava:
            return self._dados.get(campo)

    def como_json(self) -> bytes:
        with self._trava:
            return json.dumps(self._dados, ensure_ascii=False).encode("utf-8")


def _criar_handler(sala):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PASTA_UI), **kwargs)

        def do_GET(self):
            if self.path.startswith("/status"):
                corpo = sala.como_json()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            else:
                super().do_GET()

        def log_message(self, *args):
            pass  # sem isso, cada consulta da pagina poluiria o terminal

    return Handler


def iniciar_sala(porta=8765, abrir_navegador=True) -> SalaStatus:
    """Sobe o servidor numa thread daemon (morre junto com o main.py)."""
    sala = SalaStatus()
    for tentativa in range(porta, porta + 10):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", tentativa), _criar_handler(sala))
            break
        except OSError:
            continue  # porta ocupada: tenta a proxima
    else:
        raise RuntimeError(f"Nenhuma porta livre entre {porta} e {porta + 9}.")

    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Sala da squad aberta em: {url}")
    if abrir_navegador:
        webbrowser.open(url)
    return sala


def observar_guardrail(guardrail, sala):
    """Decorator: devolve o mesmo resultado do guardrail e avisa a sala quando ele reprova."""
    @wraps(guardrail)
    def guardrail_observado(output):
        aprovado, resultado = guardrail(output)
        if not aprovado:
            sala.registrar_falha(str(resultado))
        return aprovado, resultado

    return guardrail_observado
