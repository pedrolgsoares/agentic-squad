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
    r"^[ \t]*[#*]*[ \t]*SPRINT[ \t]*([12])\b",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_DOD = re.compile(
    r"^[ \t]*[#*]*[ \t]*DEFINI(?:CAO|ÇÃO)[ \t]+DE[ \t]+PRONTO\b",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_IMPEDIMENTOS = re.compile(
    r"^[ \t]*[#*]*[ \t]*IMPEDIMENTOS\b",
    flags=re.IGNORECASE | re.MULTILINE,
)

ITEM_LISTA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", flags=re.MULTILINE)

PRIORIDADES_ESPERADAS = ["MUST"] * 4 + ["SHOULD"] * 3 + ["COULD"] * 2 + ["WONT"]

# Verbos e conectores que o llama3.2 costuma usar no lugar de "quero" / "para".
# Sem isso, "gostaria de", "pra", "a fim de" e negrito reprovam a historia.
VERBO_DESEJO = r"(?:quero|gostaria(?:\s+de)?|desejo|preciso(?:\s+de)?|poderia|posso)"
CONECTOR_BENEFICIO = r"(?:para|pra|a\s+fim\s+de|de\s+(?:forma|modo)(?:\s+que)?|porque|pois|para\s+que)"

# ---- Arquiteto ----------------------------------------------------------
SECAO_STACK = re.compile(
    r"^[ \t]*[#*]*[ \t]*STACK[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_MODULOS = re.compile(
    r"^[ \t]*[#*]*[ \t]*M[OÓ]DULOS[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_ENTIDADES = re.compile(
    r"^[ \t]*[#*]*[ \t]*ENTIDADES[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
SECAO_ENDPOINTS = re.compile(
    r"^[ \t]*[#*]*[ \t]*ENDPOINTS[ \t]*[*:]*[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)

# Campos da STACK: nome para mensagens -> regex do rotulo
CAMPOS_STACK = {
    "Linguagem": r"Linguagem",
    "Framework": r"Framework",
    "Banco de dados": r"Banco(?:[ \t]+de[ \t]+dados)?",
    "Interface": r"Interface",
    "Justificativa": r"Justificativa",
}

# Modulo: - M1 | nome | responsabilidade
LINHA_MODULO = re.compile(
    r"^[ \t]*[-*•]?[ \t]*\**M(\d)\**[ \t]*\|[ \t]*(.+?)[ \t]*\|[ \t]*(.+?)[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)

# Entidade: - Usuario: id, nome, email
LINHA_ENTIDADE = re.compile(
    r"^[ \t]*[-*•][ \t]*\**([^:|\n*]+?)\**[ \t]*:[ \t]*(.+?)[ \t]*$",
    flags=re.MULTILINE,
)

# Endpoint: - GET /rota | M1 | cobre: T01.1, T01.2
LINHA_ENDPOINT = re.compile(
    r"^[ \t]*[-*•][ \t]*\**(GET|POST|PUT|DELETE)\**[ \t]+`?(/[^\s|`]*)`?[ \t]*\|"
    r"[ \t]*\**M(\d)\**[ \t]*\|[ \t]*\**cobre\**[ \t]*:[ \t]*\**(.+?)[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)

# Codigos validos do Scrum Master: 2 tarefas por historia, US-01 a US-09 (US-10 e WONT)
CODIGOS_TAREFA = {f"T{n:02d}.{s}" for n in range(1, 10) for s in (1, 2)}
MIN_TAREFAS_COBERTAS = 12  # dos 18 codigos, quantos os endpoints precisam cobrir

# Faixa de endpoints. O MAXIMO e auto-corrigido (duplicados e excesso saem
# sem nova chamada ao LLM); so o MINIMO reprova.
MIN_ENDPOINTS = 8
MAX_ENDPOINTS = 12

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
    """Retorna (acao, descricao). Versao tolerante: aceita para, que, de forma, ou sem beneficio."""
    descricao = _descricao_da_historia(bloco)
    texto_low = descricao.lower()

    # 1. Tem que ter "como" e um verbo de desejo
    if "como" not in texto_low:
        return None, descricao

    verbos = ["quero", "gostaria", "desejo", "preciso", "posso", "poderia"]
    verbo_encontrado = None
    pos_verbo = -1
    for v in verbos:
        pos = texto_low.find(v)
        if pos != -1:
            verbo_encontrado = v
            pos_verbo = pos
            break

    if verbo_encontrado is None:
        return None, descricao

    # 2. Pega tudo depois do verbo como acao
    # "Como casal quero ter um planejamento..." -> acao = "ter um planejamento..."
    acao = descricao[pos_verbo + len(verbo_encontrado):].strip()
    # tira "de", "que" inicial se sobrar, e ponto final
    acao = acao.lstrip(" :,-").rstrip(".").strip()

    if len(acao) < 5:
        return None, descricao

    return acao, descricao

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

    # --- Titulos das sprints (aceita "SPRINT 1 - Objetivo..." na mesma linha)
    sprints = {m.group(1): m for m in SECAO_SPRINT.finditer(texto)}
    if "1" not in sprints:
        return (False, "Falta o titulo 'SPRINT 1' em uma linha. Escreva 'SPRINT 1' no inicio da linha.")
    if "2" not in sprints:
        return (False, "Falta o titulo 'SPRINT 2' em uma linha. Voce parou na SPRINT 1. Use o formato curto: '- [US-05] T05.1, T05.2' sem descricao, para caber a SPRINT 2.")
    if sprints["1"].start() > sprints["2"].start():
        return (False, "A SPRINT 1 deve vir antes da SPRINT 2.")

    dod = SECAO_DOD.search(texto)
    if not dod:
        return (False, "Falta o titulo 'DEFINICAO DE PRONTO' em uma linha.")
    imp = SECAO_IMPEDIMENTOS.search(texto)
    if not imp:
        return (False, "Falta o titulo 'IMPEDIMENTOS' em uma linha.")

    # SPRINT 1 = entre SPRINT 1 e SPRINT 2
    # SPRINT 2 = da SPRINT 2 ate o fim, sem DEFINICAO / IMPEDIMENTOS
    texto_s1 = texto[sprints["1"].end():sprints["2"].start()]
    texto_s2_full = texto[sprints["2"].end():]
    texto_s2 = SECAO_DOD.split(texto_s2_full)[0]
    texto_s2 = SECAO_IMPEDIMENTOS.split(texto_s2)[0]
    texto_s1_limpo = SECAO_DOD.split(texto_s1)[0]
    texto_s1_limpo = SECAO_IMPEDIMENTOS.split(texto_s1_limpo)[0]

    # --- Objetivo de cada sprint
    for nome, trecho in (("SPRINT 1", texto_s1), ("SPRINT 2", texto_s2_full)):
        if not re.search(r"objetivo\s*:", trecho, flags=re.IGNORECASE):
            return (False, f"A {nome} esta sem a linha 'Objetivo:'.")

    # --- Historias: aceita [US-01], US-01, US 01
    def _extrair_us(trecho: str):
        return {int(m.group(1)) for m in re.finditer(r"US[-\s]?(\d{1,2})", trecho, flags=re.IGNORECASE)}

    us_s1 = _extrair_us(texto_s1_limpo)
    us_s2 = _extrair_us(texto_s2)

    if us_s1 != {1, 2, 3, 4}:
        return (False, f"A SPRINT 1 deve ter exatamente US-01, US-02, US-03 e US-04. Encontrei {sorted(us_s1)}. Escreva uma linha por historia: '- [US-01] T01.1, T01.2'.")
    if us_s2 != {5, 6, 7, 8, 9}:
        return (False, f"A SPRINT 2 deve ter exatamente US-05 a US-09. Encontrei {sorted(us_s2)}. A US-10 fica fora.")

    # --- Definicao de pronto e impedimentos
    inicio_dod = dod.end()
    fim_dod = imp.start() if imp.start() > inicio_dod else len(texto)
    if imp.start() < inicio_dod:
        fim_dod = len(texto)
    itens_dod = ITEM_LISTA.findall(texto[inicio_dod:fim_dod])
    if len(itens_dod) < 3:
        return (False, f"A DEFINICAO DE PRONTO precisa de 3 itens com '-'. Voce escreveu {len(itens_dod)}.")
    if not ITEM_LISTA.search(texto[imp.end():]):
        return (False, "IMPEDIMENTOS precisa de pelo menos 1 item com '-'.")

    return (True, output)

def _campo_stack(texto: str, padrao: str):
    """Valor de '- Rotulo: valor' (tolera negrito e ausencia do '-'). None se nao achar."""
    m = re.search(
        r"^[ \t]*[-*•]?[ \t]*\**[ \t]*" + padrao + r"[ \t]*\**[ \t]*:[ \t]*\**[ \t]*(\S.*)$",
        texto,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1).replace("*", "").strip() if m else None


def guardrail_stack(output):
    """Exige STACK com 5 campos (valor unico e real) e MODULOS com M1..M5 distintos."""
    os.makedirs("output", exist_ok=True)
    texto = output.raw

    with open("output/debug_stack.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Titulos (em qualquer ordem)
    if not SECAO_STACK.search(texto):
        return (False, "Falta o titulo 'STACK' sozinho em uma linha, sem negrito.")
    if not SECAO_MODULOS.search(texto):
        return (False, "Falta o titulo 'MODULOS' sozinho em uma linha, sem acento e sem negrito.")

    # --- Campos da stack
    for nome, padrao in CAMPOS_STACK.items():
        valor = _campo_stack(texto, padrao)
        if not valor:
            return (False, f"Falta o campo '- {nome}: <valor>' na secao STACK.")
        if "[" in valor or "]" in valor:
            return (False, f"O campo {nome} ficou com o texto do modelo: '{valor}'. Escreva o valor real, sem colchetes.")
        if nome in ("Linguagem", "Framework", "Banco de dados") and re.search(r"\bou\b", _normalizar(valor)):
            return (False, f"O campo {nome} lista alternativas: '{valor}'. Escolha UMA tecnologia.")
        if nome == "Interface" and not re.search(r"web|mobile|desktop", _normalizar(valor)):
            return (False, f"O campo Interface deve ser web, mobile ou desktop. Voce escreveu: '{valor}'.")

    # --- Modulos M1..M5
    modulos = LINHA_MODULO.findall(texto)
    numeros = sorted(int(n) for n, _, _ in modulos)
    if numeros != [1, 2, 3, 4, 5]:
        return (
            False,
            f"Encontrei os modulos {numeros}. Escreva exatamente 5 linhas no formato "
            "'- M1 | nome | responsabilidade', de M1 ate M5.",
        )

    nomes = [_normalizar(nome.replace("*", "")) for _, nome, _ in modulos]
    if any("[" in n for n in nomes):
        return (False, "Ha modulo com o texto do modelo entre colchetes. Escreva o nome real de cada modulo.")
    if len(set(nomes)) < 5:
        return (False, "Ha modulos com o mesmo nome. Os 5 modulos precisam ter nomes diferentes.")

    return (True, output)


# ---- Auxiliares de ENDPOINTS ------------------------------------------------

def _codigos_endpoint(m) -> list[str]:
    """Codigos T citados no 'cobre:' de um endpoint."""
    return [c.upper() for c in re.findall(r"T\d{2}\.\d", m.group(4), flags=re.IGNORECASE)]


def _endpoint_valido(m) -> bool:
    """Modulo M1..M5 e pelo menos 1 codigo, todos existentes."""
    codigos = _codigos_endpoint(m)
    return 1 <= int(m.group(3)) <= 5 and bool(codigos) and all(c in CODIGOS_TAREFA for c in codigos)


def _selecionar_por_cobertura(endpoints: list, limite: int) -> list:
    """Escolhe ate `limite` endpoints maximizando as tarefas cobertas (guloso).
    Em empate fica o que o modelo escreveu primeiro. Devolve na ordem original."""
    restantes = list(endpoints)
    escolhidos, cobertos = [], set()
    while restantes and len(escolhidos) < limite:
        melhor = max(
            restantes,
            key=lambda m: len((set(_codigos_endpoint(m)) & CODIGOS_TAREFA) - cobertos),
        )
        escolhidos.append(melhor)
        cobertos.update(_codigos_endpoint(melhor))
        restantes.remove(melhor)
    return sorted(escolhidos, key=lambda m: m.start())


def _remover_linhas(texto: str, matches: list) -> str:
    """Apaga do texto as linhas inteiras dos matches (de tras para frente)."""
    for m in sorted(matches, key=lambda m: m.start(), reverse=True):
        fim = m.end() + 1 if texto[m.end():m.end() + 1] == "\n" else m.end()
        texto = texto[:m.start()] + texto[fim:]
    return texto


def guardrail_contrato(output):
    """Exige ENTIDADES (3-6, 3+ campos) e ENDPOINTS (8-12) ligados a M1..M5 e a codigos T validos.
    Endpoints duplicados ou acima de 12 sao removidos aqui mesmo (auto-correcao)."""
    os.makedirs("output", exist_ok=True)
    texto = output.raw

    with open("output/debug_contrato.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # --- Titulos (em qualquer ordem)
    ent = SECAO_ENTIDADES.search(texto)
    end = SECAO_ENDPOINTS.search(texto)
    if not ent:
        return (False, "Falta o titulo 'ENTIDADES' sozinho em uma linha, sem negrito.")
    if not end:
        return (False, "Falta o titulo 'ENDPOINTS' sozinho em uma linha, sem negrito.")

    if ent.start() < end.start():
        texto_ent = texto[ent.end():end.start()]
        ini_end, fim_end = end.end(), len(texto)
    else:
        texto_ent = texto[ent.end():]
        ini_end, fim_end = end.end(), ent.start()

    # --- Entidades
    entidades = LINHA_ENTIDADE.findall(texto_ent)
    if not 3 <= len(entidades) <= 6:
        return (
            False,
            f"Encontrei {len(entidades)} entidades. Liste de 3 a 6, no formato "
            "'- Usuario: id, nome, email'.",
        )

    nomes = []
    for nome, campos in entidades:
        if "[" in nome or "[" in campos:
            return (False, f"A entidade '{nome.strip()}' ficou com o texto do modelo. Escreva nomes e campos reais.")
        lista = [c.strip() for c in campos.replace("*", "").split(",") if c.strip()]
        if len(lista) < 3:
            return (False, f"A entidade '{nome.strip()}' tem {len(lista)} campos. Escreva pelo menos 3, separados por virgula.")
        nomes.append(_normalizar(nome))
    if len(set(nomes)) < len(nomes):
        return (False, "Ha entidades repetidas. Cada entidade deve aparecer uma vez.")

    # --- Endpoints: AUTO-CORRECAO antes de validar
    # O llama3.2 tende a escrever 1 endpoint por tarefa (ate 18) e, ao receber
    # "encontrei 15", reescreve a lista inteira e soma as duas (27). Excesso
    # nao e erro de conteudo: cortamos aqui em vez de gastar outra tentativa.
    achados = list(LINHA_ENDPOINT.finditer(texto, ini_end, fim_end))

    unicos, descartar, vistos = [], [], set()
    for m in achados:
        chave = (m.group(1).upper(), m.group(2).lower().rstrip("/"))
        if chave in vistos:
            descartar.append(m)          # METODO + rota repetidos: fica o primeiro
            continue
        vistos.add(chave)
        unicos.append(m)

    if len(unicos) > MAX_ENDPOINTS:
        validos = [m for m in unicos if _endpoint_valido(m)]
        candidatos = validos if len(validos) >= MIN_ENDPOINTS else unicos
        escolhidos = _selecionar_por_cobertura(candidatos, MAX_ENDPOINTS)
        descartar += [m for m in unicos if m not in escolhidos]
        unicos = escolhidos

    if descartar:
        texto = _remover_linhas(texto, descartar)
        output.raw = texto
        with open("output/debug_contrato.txt", "w", encoding="utf-8") as f:
            f.write(texto)

    if len(unicos) < MIN_ENDPOINTS:
        return (
            False,
            f"Encontrei {len(unicos)} endpoints validos. Liste de {MIN_ENDPOINTS} a {MAX_ENDPOINTS} no formato "
            "'- GET /rota | M1 | cobre: T01.1, T01.2'. METODO so pode ser GET, POST, PUT ou DELETE.",
        )

    cobertos = set()
    for m in unicos:
        metodo, rota, modulo, _ = m.groups()
        rotulo = f"{metodo.upper()} {rota}"

        if not 1 <= int(modulo) <= 5:
            return (False, f"O endpoint {rotulo} usa o modulo M{modulo}. Use somente M1 a M5.")

        codigos = _codigos_endpoint(m)
        if not codigos:
            return (False, f"O endpoint {rotulo} nao cita nenhum codigo de tarefa. Escreva 'cobre: T01.1, T01.2'.")
        invalidos = [c for c in codigos if c not in CODIGOS_TAREFA]
        if invalidos:
            return (
                False,
                f"O endpoint {rotulo} cita codigos que nao existem: {', '.join(invalidos)}. "
                "Os codigos validos vao de T01.1 ate T09.2 (a US-10 nao tem tarefas).",
            )
        cobertos.update(codigos)

    # --- Cobertura das tarefas do Scrum Master
    # A dica de citar varios codigos no MESMO endpoint evita que o modelo
    # resolva a cobertura criando endpoints novos (e estoure o maximo).
    if len(cobertos) < MIN_TAREFAS_COBERTAS:
        faltam = sorted(CODIGOS_TAREFA - cobertos)
        return (
            False,
            f"Os endpoints cobrem so {len(cobertos)} das 18 tarefas; cubra pelo menos {MIN_TAREFAS_COBERTAS}. "
            f"Tarefas sem endpoint: {', '.join(faltam[:8])}{'...' if len(faltam) > 8 else ''}. "
            f"NAO crie endpoints novos (maximo {MAX_ENDPOINTS}): acrescente esses codigos no 'cobre:' "
            "dos endpoints que ja existem, por exemplo 'cobre: T01.1, T01.2, T05.1'.",
        )

    return (True, output)