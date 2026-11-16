# main.py
# Teste da Squad (PO + Scrum Master + Arquiteto) com LLM Local via Ollama
# Rode: python main.py
#
# Fluxo:
#   ideia -> validacao de entrada -> checagem de tamanho
#         -> DESCOBERTA (guardrail) -> BACKLOG (guardrail)      [PO]
#         -> TAREFAS (guardrail)    -> SPRINT (guardrail)       [Scrum Master]
#         -> STACK (guardrail)      -> CONTRATO (guardrail)     [Arquiteto]
#         -> output/squad.md

import os
from crewai import Crew, Task, LLM
from agents.po_agent import create_po_agent, DISCOVERY_PROMPT, BACKLOG_PROMPT
from agents.scrum_agent import create_scrum_agent, TASKS_PROMPT, SPRINT_PROMPT
from agents.architect_agent import create_architect_agent, STACK_PROMPT, CONTRACT_PROMPT
from configs.guardrails import (
    validar_ideia,
    checar_tamanho_prompt,
    guardrail_descoberta,
    guardrail_backlog,
    guardrail_tarefas,
    guardrail_sprint,
    guardrail_stack,
    guardrail_contrato,
)

from ui_server import iniciar_sala, observar_guardrail
# 1. CONFIGURA O LLM LOCAL
# Certifique-se que voce ja rodou no terminal:
#   ollama pull llama3.2
#   ollama serve
# Se o log do ollama mostrar "truncating input prompt", o num_ctx nao chegou
# ao servidor: use OLLAMA_CONTEXT_LENGTH=8192 antes do "ollama serve".

llm = LLM(
    model="ollama/llama3.2",
    base_url="http://localhost:11434",
    temperature=0.3,  # modelo pequeno + saida estruturada: menos aleatoriedade
    context_window_size=8192,     # cabe prompt + instrucoes do CrewAI + contexto + resposta
    extra_body={"options": {"num_ctx": 8192}}, # Envia o parâmetro direto para a API do Ollama
)

IDEIA_PADRAO = "App de controle de gastos pessoais com categorias e relatorios mensais"

# [SALA] Depois que cada etapa e aprovada: mensagem do diario e proxima etapa.
# CORRECAO: faltava "sprint" -> "stack". Sem ela a sala ficava presa em "sprint"
# e o Scrum Master aparecia refazendo os erros do Arquiteto.
# "contrato" nao entra aqui: depois dele o main() publica a etapa "fim".
PROXIMA_ETAPA = {
    "descoberta": ("Funcionalidades aprovadas. Começando as user stories.", "backlog"),
    "backlog": ("Backlog aprovado. Scrum Master quebrando em tarefas.", "tarefas"),
    "tarefas": ("Tarefas aprovadas. Montando as sprints.", "sprint"),
    "sprint": ("Sprints aprovadas. Arquiteto escolhendo a stack.", "stack"),
    "stack": ("Stack aprovada. Arquiteto montando o contrato técnico.", "contrato"),
}


def pedir_ideia() -> str:
    """Guardrail de entrada: repete a pergunta ate a ideia ser aceitavel."""
    while True:
        idea = input("Qual a sua ideia de produto? Ex: App de controle de gastos\n> ").strip()
        if not idea:
            print(f"Usando ideia padrao: {IDEIA_PADRAO}")
            return IDEIA_PADRAO
        erros = validar_ideia(idea)
        if not erros:
            return idea
        print("\nA ideia precisa de mais detalhes:")
        for erro in erros:
            print(f"  - {erro}")
        print("")

def esperar_enter():
    # [SALA] O servidor roda numa thread daemon: se o main.py terminar, a pagina para.
    input("\nA sala continua aberta no navegador. Pressione Enter para encerrar...")

def main():
    print("=" * 60)
    print("AGENTIC SQUAD - PO + SCRUM MASTER + ARQUITETO")
    print("LLM Local: Ollama + Llama 3.2")
    print("=" * 60)
    print("")

    # [SALA] Abre a sala antes de pedir a ideia: o PO aparece "aguardando"
    sala = iniciar_sala()

    # 2. PEGA E VALIDA A IDEIA
    idea = pedir_ideia()
    descricao_descoberta = DISCOVERY_PROMPT.format(idea=idea)
    descricao_backlog = BACKLOG_PROMPT.format(idea=idea)
    descricao_tarefas = TASKS_PROMPT.format(idea=idea)
    descricao_sprint = SPRINT_PROMPT.format(idea=idea)
    descricao_stack = STACK_PROMPT.format(idea=idea)
    descricao_contrato = CONTRACT_PROMPT.format(idea=idea)
    try:
        checar_tamanho_prompt(descricao_descoberta)
        checar_tamanho_prompt(descricao_backlog)
        checar_tamanho_prompt(descricao_tarefas)
        checar_tamanho_prompt(descricao_sprint)
        checar_tamanho_prompt(descricao_stack)
        checar_tamanho_prompt(descricao_contrato)
    except ValueError as erro:
        print(f"\n{erro}")
        sala.publicar(str(erro), tipo="erro", estado="erro", ideia=idea)
        esperar_enter()
        return

    sala.publicar(
        f"Ideia recebida: {idea}",
        estado="pensando", etapa="descoberta", ideia=idea, tentativa=0, motivo="",
    )

    # 3. CRIA OS AGENTES
    po_agent = create_po_agent(llm)
    scrum_agent = create_scrum_agent(llm)
    architect_agent = create_architect_agent(llm)

    # 4. CRIA AS TAREFAS (prompt chaining)
    # A etapa mostrada na sala vem do task_callback + PROXIMA_ETAPA,
    # entao o observar_guardrail continua com 2 argumentos.
    # --- PO ---
    descoberta_task = Task(
        description=descricao_descoberta,
        expected_output="Visao do produto, 2 personas e 10 funcionalidades numeradas e distintas",
        agent=po_agent,
        guardrail=observar_guardrail(guardrail_descoberta, sala),
    )

    backlog_task = Task(
        description=descricao_backlog,
        expected_output=(
            "10 user stories com prioridade, criterios de aceite e estimativa, "
            "seguidas de priorizacao e riscos"
        ),
        agent=po_agent,
        context=[descoberta_task],  # recebe visao, personas e funcionalidades
        guardrail=observar_guardrail(guardrail_backlog, sala),
    )

    # --- Scrum Master ---
    tarefas_task = Task(
        description=descricao_tarefas,
        expected_output="2 tarefas tecnicas com esforco P/M/G para cada historia de US-01 a US-09",
        agent=scrum_agent,
        context=[backlog_task],  # recebe as 10 user stories do PO
        guardrail=observar_guardrail(guardrail_tarefas, sala),
    )

    sprint_task = Task(
        description=descricao_sprint,
        expected_output="Plano de 2 sprints, definicao de pronto e impedimentos",
        agent=scrum_agent,
        context=[tarefas_task],  # recebe so as tarefas
        guardrail=observar_guardrail(guardrail_sprint, sala),
    )

    # --- Arquiteto ---
    stack_task = Task(
        description=descricao_stack,
        expected_output="Stack (linguagem, framework, banco, interface, justificativa) e 5 modulos",
        agent=architect_agent,
        context=[tarefas_task],  # precisa das tarefas T01.1... com descricao
        guardrail=observar_guardrail(guardrail_stack, sala),
    )

    contrato_task = Task(
        description=descricao_contrato,
        expected_output="Entidades e endpoints ligados aos modulos e aos codigos de tarefa",
        agent=architect_agent,
        context=[tarefas_task, stack_task],
        guardrail=observar_guardrail(guardrail_contrato, sala),
    )

    def ao_concluir_tarefa(output):
        # [SALA] Chamado pelo CrewAI depois de cada tarefa aprovada
        etapa = sala.get("etapa")
        if etapa in PROXIMA_ETAPA:
            mensagem, proxima = PROXIMA_ETAPA[etapa]
            sala.publicar(
                mensagem,
                tipo="ok", estado="escrevendo", etapa=proxima, tentativa=0, motivo="",
            )

    # 5. MONTA O CREW COM O PO, O SCRUM MASTER E O ARQUITETO
    crew = Crew(
        agents=[po_agent, scrum_agent, architect_agent],
        tasks=[descoberta_task, backlog_task, tarefas_task, sprint_task, stack_task, contrato_task],
        verbose=True,
        task_callback=ao_concluir_tarefa,  # [SALA]
    )

    print("\nSquad trabalhando... aguarde...\n")
    try:
        result = crew.kickoff()
    except Exception as erro:
        # Se o guardrail esgotar as tentativas, o CrewAI levanta excecao
        print(f"\nA squad nao conseguiu gerar um resultado valido: {erro}")
        print("Tente detalhar mais a ideia ou rodar novamente.")
        # [SALA] Mostra "Parou com erro" no agente da etapa atual, em vez de a
        # pagina ficar congelada em "Refazendo" e cair quando o script termina
        sala.publicar(
            f"Parou na etapa {sala.get('etapa')}: {erro}",
            tipo="erro", estado="erro",
        )
        esperar_enter()
        return

    # 6. SALVA O RESULTADO (as seis etapas, nao so a ultima)
    documento = "\n\n".join(t.raw for t in result.tasks_output)

    os.makedirs("output", exist_ok=True)
    with open("output/squad.md", "w", encoding="utf-8") as f:
        f.write(documento)

    sala.publicar(
        "Backlog, sprints e contrato técnico salvos em output/squad.md",
        tipo="ok", estado="pronto", etapa="fim",
    )

    print("\n" + "=" * 60)
    print("PRONTO! Resultado salvo em: output/squad.md")
    print("=" * 60)
    print(documento)
    esperar_enter()

if __name__ == "__main__":
    main()