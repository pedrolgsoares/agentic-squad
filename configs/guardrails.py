# guardrails.py
# Validacoes do Agentic Squad
#   - Entrada: barra ideias vagas e prompts grandes demais ANTES de chamar o LLM
#   - Saida:   usadas no parametro guardrail das Tasks; se falharem, o CrewAI
#              refaz a tarefa enviando a mensagem de erro como feedback ao modelo

import re
import unicodedata
from collections import Counter
import os

MIN_PALAVRAS = 6

# num_ctx=8192 no main.py. Reserva ~3500 tokens para o prompt da tarefa;
# o resto fica para as instrucoes internas do CrewAI, o contexto da
# etapa anterior e a resposta do modelo.
LIMITE_TOKENS_PROMPT = 3500

# Titulos de secao so valem quando estao SOZINHOS na linha (com ou sem **).
# Assim a palavra "priorizacao" numa frase de abertura nao corta o texto.
SECAO_PRIORIZACAO = re.compile(
    r"^[ \t]*\**[ \t]*PRIORIZA(?:CAO|ÇÃO)[ \t]*\**[ \t]*:?[ \t]*\**[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_RISCOS = re.compile(
    r"^[ \t]*\**[ \t]*RISCOS[ \t]*\**[ \t]*:?[ \t]*\**[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)

# Cabecalho de historia: so no INICIO da linha, assim a lista numerada da
# PRIORIZACAO ("1. [US-01] MUST - ...") nao e contada como historia.
CABECALHO_US = re.compile(
    r"^[ \t]*\**\[US-(\d{2})\]\**[ \t]*"
    r"(?:\[Prioridade:\s*[A-Za-z']+\]|MUST|SHOULD|COULD|WON'?T)?[ \t]*\**",
    flags=re.IGNORECASE | re.MULTILINE,
)

PRIORIDADES_ESPERADAS = ["MUST"] * 4 + ["SHOULD"] * 3 + ["COULD"] * 2 + ["WONT"]

def _normalizar(texto: str) -> str:
    """Minusculas, sem acentos e com espacos colapsados, para comparar textos."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()

# ---------------------------------------------------------------- ENTRADA

def validar_ideia(idea: str) -> list[str]:
    """Retorna a lista de problemas da ideia. Lista vazia = ideia valida."""
    erros = []
    if len(idea.split()) < MIN_PALAVRAS:
        erros.append(
            f"Use pelo menos {MIN_PALAVRAS} palavras: diga o que o produto faz e para quem."
        )
    if "hello world" in _normalizar(idea):
        erros.append("Um hello world nao tem funcionalidades suficientes para 10 historias.")
    return erros

def estimar_tokens(texto: str) -> int:
    """Estimativa conservadora para portugues (~3 caracteres por token)."""
    return len(texto) // 3

def checar_tamanho_prompt(prompt: str) -> None:
    tokens = estimar_tokens(prompt)
    if tokens > LIMITE_TOKENS_PROMPT:
        raise ValueError(
            f"Prompt com ~{tokens} tokens excede o limite de {LIMITE_TOKENS_PROMPT}. "
            "Resuma a ideia."
        )

# ------------------------------------------------------------------ SAIDA

def guardrail_descoberta(output):
    """Exige a secao de personas e 10 funcionalidades numeradas e distintas."""
    texto = output.raw

    # DEBUG da Etapa 1 - igual ao da Etapa 2
    with open("output/debug_descoberta.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # CORRECAO: aceita PERSONAS, PERSONA, PERFIS, USUARIOS, PUBLICO-ALVO
    # O llama3.2 troca o nome da secao, entao nao pode exigir so PERSONAS
    if not re.search(r"PERSONAS?|PERFIS|USU[AÁ]RIOS|P[UÚ]BLICO", texto, flags=re.IGNORECASE):
        return (False, "Falta a secao 2. PERSONAS. Escreva exatamente o titulo '2. PERSONAS' em uma linha.")

    partes = re.split(r"funcionalidades", texto, flags=re.IGNORECASE)
    if len(partes) < 2:
        return (False, "Falta a secao 3. FUNCIONALIDADES. Escreva exatamente o titulo '3. FUNCIONALIDADES' em uma linha.")

    itens = re.findall(r"^\s*\d{1,2}\s*[.)-]\s*(.+)$", partes[-1], flags=re.MULTILINE)
    itens = [_normalizar(i) for i in itens][:10]

    if len(itens) < 10:
        return (False, f"Encontrei {len(itens)} funcionalidades. Liste exatamente 10 funcionalidades numeradas de 1 a 10.")
    if len(set(itens)) < 10:
        return (False, "Ha funcionalidades repetidas. Reescreva as 10 todas diferentes.")
    return (True, output)

def guardrail_backlog(output):
    os.makedirs("output", exist_ok=True)
    texto = output.raw

    with open("output/debug_ultima_resposta.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Normaliza o rotulo: **US-01], US-01], US 01 -> [US-01]
    texto = re.sub(
        r"\*{0,2}\[?(?<![A-Za-z0-9])US[-\s]?(\d{1,2})\]?\*{0,2}",
        lambda m: f"[US-{int(m.group(1)):02d}]",
        texto,
        flags=re.IGNORECASE,
    )

    # --- Auto-corrige a prioridade pela POSICAO (as 10 primeiras historias).
    contador = {"i": 0}

    def _corrige_cabecalho(m):
        i = contador["i"]
        contador["i"] += 1
        if i >= 10:
            return m.group(0)
        return f"[US-{m.group(1)}] {PRIORIDADES_ESPERADAS[i]}"

    texto = CABECALHO_US.sub(_corrige_cabecalho, texto)

    output.raw = texto
    with open("output/debug_ultima_resposta.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Separa a parte das historias (antes de PRIORIZACAO/RISCOS)
    parte_historias = SECAO_PRIORIZACAO.split(texto)[0]
    parte_historias = SECAO_RISCOS.split(parte_historias)[0]

    # --- Localiza os cabecalhos de cada historia
    cabecalhos = list(CABECALHO_US.finditer(parte_historias))

    if len(cabecalhos) != 10:
        return (
            False,
            f"Encontrei {len(cabecalhos)} historias. Escreva exatamente 10 historias, "
            "cada uma comecando com [US-01] ate [US-10], sem texto de introducao antes.",
        )

    numeros = [int(m.group(1)) for m in cabecalhos]
    if numeros != list(range(1, 11)):
        return (False, "As historias devem ser numeradas em ordem, de [US-01] ate [US-10].")

    # --- Monta os blocos (do fim de um cabecalho ate o inicio do proximo)
    blocos = []
    for idx, m in enumerate(cabecalhos):
        fim = cabecalhos[idx + 1].start() if idx + 1 < len(cabecalhos) else len(parte_historias)
        blocos.append(parte_historias[m.end():fim])

    acoes = []
    for i, bloco in enumerate(blocos, start=1):
        rotulo = f"US-{i:02d}"

        # Linha "Como ... quero ... para ..."
        linha = re.search(
            r"^[^\n]*\bComo\b[^\n]*\bquero\b[^\n]*$",
            bloco,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if not linha:
            return (False, f"{rotulo} fora do formato 'Como ... quero ... para ...'.")

        if i == 10:
            # WONT: aceita "nao quero ... pois ..." ou "quero ... para ..."
            acao = re.search(
                r"\bquero\s+(.+?)(?:\s*,?\s+(?:para|pois)\s|$)",
                linha.group(0),
                flags=re.IGNORECASE,
            )
        else:
            acao = re.search(r"\bquero\s+(.+?)\s+para\s", linha.group(0), flags=re.IGNORECASE)
        if not acao:
            return (False, f"{rotulo} fora do formato 'Como ... quero ... para ...'.")
        acoes.append(_normalizar(acao.group(1)))

        # A US-10 (WONT) nao sera implementada: criterios sao opcionais nela.
        # O continue vem DEPOIS de acoes.append, entao ela entra no check de repetidas.
        if i == 10:
            continue

        # Criterios de aceite: so conta o que vem DEPOIS do titulo
        achou = re.search(r"crit[eé]rios de aceite", bloco, flags=re.IGNORECASE)
        if not achou:
            return (
                False,
                f"{rotulo} esta sem Criterios de Aceite. Escreva a linha 'Criterios de Aceite:' "
                "e depois 3 linhas comecando com '-'.",
            )

        trecho_criterios = bloco[achou.end():]
        trecho_criterios = re.split(
            r"^\s*\**\s*Estimativa", trecho_criterios, flags=re.IGNORECASE | re.MULTILINE
        )[0]

        criterios = re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+\S", trecho_criterios, flags=re.MULTILINE)
        if len(criterios) < 3:
            return (
                False,
                f"{rotulo} precisa de 3 criterios com '-'. Voce escreveu {len(criterios)}.",
            )

    # --- Acoes repetidas
    if len(set(acoes)) < 10:
        return (False, "Ha historias com a mesma acao 'quero...'. Cada historia precisa de uma acao diferente.")

    # --- Secao RISCOS (em linha propria)
    if not SECAO_RISCOS.search(texto):
        return (False, "Falta a secao RISCOS depois das historias. Escreva 'RISCOS' sozinho em uma linha.")

    return (True, output)