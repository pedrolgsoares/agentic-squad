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
# Rotulo de historia em qualquer formato: **US-01], US-01], US 01 -> [US-01]
ROTULO_US = re.compile(
    r"\*{0,2}\[?(?<![A-Za-z0-9])US[-\s]?(\d{1,2})\]?\*{0,2}",
    flags=re.IGNORECASE,
)

# Titulo de historia na etapa de tarefas: [US-01] sozinho no inicio da linha
TITULO_US = re.compile(r"^[ \t]*[#*]*[ \t]*\[US-(\d{2})\]", flags=re.MULTILINE)

# Linha de tarefa: - T01.1 | descricao | Esforco: P
LINHA_TAREFA = re.compile(
    r"^[ \t]*[-*•][ \t]*(?:\[US-\d{2}\]\s*)?\**T(\d{2})\.(\d)\**[ \t]*\|[ \t]*(.+?)[ \t]*\|[ \t]*Esfor[cç]o:[ \t]*\**([PMG])\b",
    flags=re.IGNORECASE | re.MULTILINE,
)

SECAO_SPRINT = re.compile(
    r"^[ \t]*[#*]*[ \t]*SPRINT[ \t]*([12])[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_DOD = re.compile(
    r"^[ \t]*[#*]*[ \t]*DEFINI(?:CAO|ÇÃO)[ \t]+DE[ \t]+PRONTO[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_IMPEDIMENTOS = re.compile(
    r"^[ \t]*[#*]*[ \t]*IMPEDIMENTOS[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)

ITEM_LISTA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", flags=re.MULTILINE)

PRIORIDADES_ESPERADAS = ["MUST"] * 4 + ["SHOULD"] * 3 + ["COULD"] * 2 + ["WONT"]

# Verbos e conectores que o llama3.2 costuma usar no lugar de "quero" / "para".
# Sem isso, "gostaria de", "pra", "a fim de" e negrito reprovam a historia.
VERBO_DESEJO = r"(?:quero|gostaria(?:\s+de)?|desejo|preciso(?:\s+de)?|poderia|posso)"
CONECTOR_BENEFICIO = r"(?:para|pra|a\s+fim\s+de|de\s+(?:forma|modo)\s+que|porque|pois)"

def _normalizar(texto: str) -> str:
    """Minusculas, sem acentos e com espacos colapsados, para comparar textos."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()

def _descricao_da_historia(bloco: str) -> str:
    """Texto antes dos Criterios de Aceite, sem negrito e em uma linha so.
    Resolve quebras de linha no meio da frase e '**quero**'."""
    descricao = re.split(r"crit[eé]rios de aceite", bloco, flags=re.IGNORECASE)[0]
    descricao = descricao.replace("*", "")
    return " ".join(descricao.split())

def _extrair_acao(bloco: str, wont: bool = False):
    """Retorna (acao, descricao). acao=None se a historia estiver fora do formato.
    Na WONT o beneficio e opcional ('nao quero X' basta)."""
    descricao = _descricao_da_historia(bloco)
    fim = r"(?:\s*,?\s+" + CONECTOR_BENEFICIO + r"\s" + (r"|\s*[.;]?\s*$)" if wont else r")")
    m = re.search(
        r"\bComo\b.+?\b" + VERBO_DESEJO + r"\s+(.+?)" + fim,
        descricao + " ",
        flags=re.IGNORECASE,
    )
    return (m.group(1) if m else None), descricao

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
    os.makedirs("output", exist_ok=True)
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

        # Frase "Como ... quero ... para ..." (tolerante a variacoes do modelo).
        # O feedback mostra o que o modelo escreveu, para a nova tentativa
        # nao repetir o mesmo texto.
        acao, descricao = _extrair_acao(bloco, wont=(i == 10))
        if not acao:
            return (
                False,
                f"{rotulo} fora do formato. Escreva em UMA linha: "
                f"'Como <persona>, quero <acao> para <beneficio>.' "
                f"Voce escreveu: '{descricao[:160]}'",
            )
        acoes.append(_normalizar(acao))

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


def guardrail_tarefas(output):
    """Exige [US-01]..[US-10] e 2 tarefas T<US>.<1|2> com esforco P/M/G para US-01..US-09."""
    os.makedirs("output", exist_ok=True)

    texto = ROTULO_US.sub(lambda m: f"[US-{int(m.group(1)):02d}]", output.raw)
    output.raw = texto

    with open("output/debug_tarefas.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Titulos das historias
    titulos = [int(n) for n in TITULO_US.findall(texto)]
    if titulos != list(range(1, 11)):
        return (
            False,
            f"Encontrei os titulos {titulos}. Escreva [US-01] ate [US-10], cada um sozinho "
            "em uma linha e em ordem, sem texto de introducao antes.",
        )

    # --- Tarefas, agrupadas pelo numero da historia no codigo (T03.1 -> US-03)
    tarefas = LINHA_TAREFA.findall(texto)
    por_historia = {}
    for us, seq, descricao, esforco in tarefas:
        por_historia.setdefault(int(us), []).append(f"T{us}.{seq}")

    for n in range(1, 10):
        esperado = [f"T{n:02d}.1", f"T{n:02d}.2"]
        achado = sorted(por_historia.get(n, []))
        if achado != esperado:
            return (
                False,
                f"A US-{n:02d} precisa de exatamente 2 tarefas: '- {esperado[0]} | tarefa | Esforco: P' "
                f"e '- {esperado[1]} | tarefa | Esforco: M'. Encontrei: {achado or 'nenhuma'}.",
            )

    # --- Tarefas repetidas: so e erro se repetir DENTRO da mesma US
    # "Criar tela" em US-01 e em US-02 nao e erro, e padrao do projeto
    # Erro e: T01.1 e T01.2 com a mesma descricao
    vistos = set()
    for us, seq, descricao, esforco in tarefas:
        chave = (int(us), _normalizar(descricao))
        if chave in vistos:
            return (False, f"A US-{int(us):02d} tem 2 tarefas com a mesma descricao: '{descricao}'. Mude uma delas.")
        vistos.add(chave)

    # --- US-10 (WONT) fica fora da sprint
    if "fora da sprint" not in _normalizar(texto):
        return (False, "Falta a linha '- FORA DA SPRINT: ...' abaixo de [US-10].")

    return (True, output)


def guardrail_sprint(output):
    """Exige SPRINT 1 (US-01..04), SPRINT 2 (US-05..09), DEFINICAO DE PRONTO e IMPEDIMENTOS."""
    os.makedirs("output", exist_ok=True)

    texto = ROTULO_US.sub(lambda m: f"[US-{int(m.group(1)):02d}]", output.raw)
    output.raw = texto

    with open("output/debug_sprint.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Titulos das sprints
    sprints = {m.group(1): m for m in SECAO_SPRINT.finditer(texto)}
    if "1" not in sprints:
        return (False, "Falta o titulo 'SPRINT 1' sozinho em uma linha.")
    if "2" not in sprints:
        return (False, "Falta o titulo 'SPRINT 2' sozinho em uma linha. Voce parou na SPRINT 1. Use o formato curto: '- [US-05] T05.1, T05.2' sem descricao, para caber a SPRINT 2.")
    if sprints["1"].start() > sprints["2"].start():
        return (False, "A SPRINT 1 deve vir antes da SPRINT 2.")

    # CORRECAO: DEFINICAO DE PRONTO pode estar em qualquer lugar depois da SPRINT 1
    # O modelo coloca antes da SPRINT 2, nao depois. Nao pode exigir que seja depois da SPRINT 2.
    dod = SECAO_DOD.search(texto)
    if not dod:
        return (False, "Falta o titulo 'DEFINICAO DE PRONTO' sozinho em uma linha.")

    imp = SECAO_IMPEDIMENTOS.search(texto)
    if not imp:
        return (False, "Falta o titulo 'IMPEDIMENTOS' sozinho em uma linha.")

    # CORRECAO: SPRINT 1 = entre SPRINT 1 e SPRINT 2
    # SPRINT 2 = da SPRINT 2 ate o fim, MAS sem contar DEFINICAO/IMPEDIMENTOS se eles vierem depois
    texto_s1 = texto[sprints["1"].end():sprints["2"].start()]
    texto_s2_full = texto[sprints["2"].end():]
    # Remove DEFINICAO e IMPEDIMENTOS do texto da SPRINT 2 para nao confundir a contagem
    texto_s2 = SECAO_DOD.split(texto_s2_full)[0]
    texto_s2 = SECAO_IMPEDIMENTOS.split(texto_s2)[0]

    # Se DEFINICAO estava antes da SPRINT 2, ela estava dentro de texto_s1. Remove tambem.
    texto_s1_limpo = SECAO_DOD.split(texto_s1)[0]
    texto_s1_limpo = SECAO_IMPEDIMENTOS.split(texto_s1_limpo)[0]

    # --- Objetivo de cada sprint
    for nome, trecho in (("SPRINT 1", texto_s1), ("SPRINT 2", texto_s2_full)):
        if not re.search(r"objetivo\s*:", trecho, flags=re.IGNORECASE):
            return (False, f"A {nome} esta sem a linha 'Objetivo:'.")

    # --- Historias de cada sprint (divisao fixa por posicao)
    us_s1 = {int(n) for n in re.findall(r"\[US-(\d{2})\]", texto_s1_limpo)}
    us_s2 = {int(n) for n in re.findall(r"\[US-(\d{2})\]", texto_s2)}

    if us_s1 != {1, 2, 3, 4}:
        return (False, f"A SPRINT 1 deve ter exatamente US-01, US-02, US-03 e US-04. Encontrei {sorted(us_s1)}.")
    if us_s2 != {5, 6, 7, 8, 9}:
        return (False, f"A SPRINT 2 deve ter exatamente US-05 a US-09. Encontrei {sorted(us_s2)}. A US-10 fica fora.")

    # --- Definicao de pronto e impedimentos - conta em qualquer lugar do texto
    # Pega o trecho depois de DEFINICAO ate IMPEDIMENTOS ou fim
    inicio_dod = dod.end()
    fim_dod = imp.start() if imp.start() > inicio_dod else len(texto)
    # Se IMPEDIMENTOS veio antes de DEFINICAO, pega ate o fim
    if imp.start() < inicio_dod:
        fim_dod = len(texto)
    itens_dod = ITEM_LISTA.findall(texto[inicio_dod:fim_dod])
    if len(itens_dod) < 3:
        return (False, f"A DEFINICAO DE PRONTO precisa de 3 itens com '-'. Voce escreveu {len(itens_dod)}.")

    if not ITEM_LISTA.search(texto[imp.end():]):
        return (False, "IMPEDIMENTOS precisa de pelo menos 1 item com '-'.")

    return (True, output)