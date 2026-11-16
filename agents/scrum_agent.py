# agents/scrum_agent.py
# Agente Scrum Master do Agentic Squad
# Responsavel por transformar o Product Backlog do PO em tarefas e sprints.
#
# O trabalho e dividido em 2 etapas (prompt chaining), igual ao PO, porque um
# modelo pequeno como o llama3.2 (3B) se perde em saidas longas de uma vez so:
#   1. TAREFAS: cada user story vira 2 tarefas tecnicas com esforco P/M/G
#   2. SPRINT:  plano de 2 sprints + definicao de pronto + impedimentos

from crewai import Agent

def create_scrum_agent(llm):
    """
    Cria o agente Scrum Master.
    Recebe o LLM configurado no main.py
    """
    return Agent(
        role="Scrum Master Senior",
        goal=(
            "Transformar o Product Backlog em tarefas tecnicas pequenas e em um "
            "plano de sprints realista, pronto para o time de desenvolvimento."
        ),
        backstory=(
            "Voce e um Scrum Master com 10 anos de experiencia em times de software. "
            "Voce quebra user stories em tarefas tecnicas pequenas, com esforco "
            "estimado, e organiza as sprints respeitando a prioridade MoSCoW do PO. "
            "Voce segue formatos pedidos a risca e responde sempre em portugues brasileiro."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

# ETAPA 1: TAREFAS
# Recebe o backlog do PO via context. Sao sempre 2 tarefas por historia
# (US-01 a US-09) e a US-10 (WONT) fica fora: regra fixa que o modelo copia
# com facilidade e o guardrail confere por codigo.
TASKS_PROMPT = """
Voce e o Scrum Master Senior deste projeto.

IDEIA ORIGINAL: {idea}

Voce recebeu o Product Backlog do PO: 10 user stories, de [US-01] a [US-10].
Sua tarefa agora e quebrar CADA historia de US-01 ate US-09 em EXATAMENTE 2 tarefas tecnicas.
A US-10 e WONT: nao tem tarefas.

Nao invente historias. Nao troque de produto. Nao escreva criterios de aceite.
Comece direto em [US-01], sem frase de introducao.

FORMATO OBRIGATORIO - copie exatamente assim:

[US-01]
- T01.1 | [tarefa tecnica curta, comecando com verbo] | Esforco: P
- T01.2 | [tarefa tecnica curta, comecando com verbo] | Esforco: M

[US-02]
- T02.1 | [tarefa tecnica curta, comecando com verbo] | Esforco: M
- T02.2 | [tarefa tecnica curta, comecando com verbo] | Esforco: G

(continue assim ate a [US-09])

[US-10]
- FORA DA SPRINT: historia WONT, nao sera feita nesta versao.

REGRAS DE SCRUM - OBRIGATORIAS e :
1. Cada titulo [US-01], [US-02]... fica SOZINHO em uma linha.
2. O codigo da tarefa usa o numero da historia: US-03 tem T03.1 e T03.2, US-07 tem T07.1 e T07.2.
3. Esforco so pode ser P, M ou G.
4. Tarefa e trabalho tecnico (criar endpoint, montar tela, configurar notificacao). Nao copie o texto da user story.
5. Nunca repita a mesma descricao dentro da mesma US. Inclua o nome da funcionalidade em cada tarefa.
   Exemplo certo:
   - T01.1 | Criar tela de login do cliente | Esforco: P
   - T02.1 | Criar tela de login do entregador | Esforco: P
   Exemplo errado (NAO FACA):
   - T01.1 | Criar tela | Esforco: P
   - T01.2 | Criar tela | Esforco: P
6. Use sempre '-' no inicio da linha e '|' para separar as 3 partes.
"""

# ETAPA 2: SPRINT
# Recebe as tarefas da etapa 1 via context.
# A divisao das sprints e regra de POSICAO (igual a prioridade no backlog):
# o modelo so precisa copiar quais historias vao em cada sprint.
SPRINT_PROMPT = """
Voce e o Scrum Master Senior deste projeto.

IDEIA ORIGINAL: {idea}

Voce ja quebrou as historias em tarefas na etapa anterior.
Agora monte o plano de 2 sprints.

DIVISAO FIXA - COPIE SEM TROCAR NADA:
- SPRINT 1: US-01, US-02, US-03, US-04
- SPRINT 2: US-05, US-06, US-07, US-08, US-09
- A US-10 NAO entra em nenhuma sprint.

Comece direto em SPRINT 1, sem frase de introducao.

FORMATO OBRIGATORIO - copie exatamente assim, NAO MUDE NADA:

SPRINT 1
Objetivo: [uma frase curta]
- [US-01] T01.1, T01.2
- [US-02] T02.1, T02.2
- [US-03] T03.1, T03.2
- [US-04] T04.1, T04.2

SPRINT 2
Objetivo: [uma frase curta]
- [US-05] T05.1, T05.2
- [US-06] T06.1, T06.2
- [US-07] T07.1, T07.2
- [US-08] T08.1, T08.2
- [US-09] T09.1, T09.2

DEFINICAO DE PRONTO
- [item curto 1]
- [item curto 2]
- [item curto 3]

IMPEDIMENTOS
- [item curto 1]
- [item curto 2]

REGRAS DE SCRUM - OBRIGATORIAS:
1. PROIBIDO repetir a descricao da tarefa. Use SOMENTE o codigo: T01.1, T01.2. NUNCA escreva "| Criar tela..." ou "| Esforco: P" nesta etapa.
2. PROIBIDO copiar as REGRAS no final. Termine em IMPEDIMENTOS e PARE.
3. Os titulos SPRINT 1, SPRINT 2, DEFINICAO DE PRONTO e IMPEDIMENTOS ficam SOZINHOS em uma linha, sem acento e sem negrito.
4. Cada historia aparece UMA vez, na sprint indicada acima.
5. Objetivo e DEFINICAO DE PRONTO com no maximo 10 palavras cada.
"""