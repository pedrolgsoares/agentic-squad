# main.py
# Teste do Agente PO com LLM Local via Ollama
# Rode: python main.py
#
# Fluxo:
#   ideia -> validacao de entrada -> checagem de tamanho
#         -> DESCOBERTA (guardrail) -> BACKLOG (guardrail) -> output/backlog_po.md

import os
from crewai import Crew, Task, LLM
from agents.po_agent import create_po_agent, DISCOVERY_PROMPT, BACKLOG_PROMPT
from configs.guardrails import (
    validar_ideia,
    checar_tamanho_prompt,
    guardrail_descoberta,
    guardrail_backlog,
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
    print("AGENTIC SQUAD - TESTE DO PO")
    print("LLM Local: Ollama + Llama 3.2")
    print("=" * 60)
    print("")

    # [SALA] Abre a sala antes de pedir a ideia: o PO aparece "aguardando"
    sala = iniciar_sala()

    # 2. PEGA E VALIDA A IDEIA
    idea = pedir_ideia()
    descricao_descoberta = DISCOVERY_PROMPT.format(idea=idea)
    descricao_backlog = BACKLOG_PROMPT.format(idea=idea)

    try:
        checar_tamanho_prompt(descricao_descoberta)
        checar_tamanho_prompt(descricao_backlog)
    except ValueError as erro:
        print(f"\n{erro}")
        sala.publicar(str(erro), tipo="erro", estado="erro", ideia=idea)
        esperar_enter()
        return

    sala.publicar(
        f"Ideia recebida: {idea}",
        estado="pensando", etapa="descoberta", ideia=idea, tentativa=0, motivo="",
    )

    # 3. CRIA O AGENTE PO
    po_agent = create_po_agent(llm)

    # 4. CRIA AS TAREFAS (prompt chaining)
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
    
    def ao_concluir_tarefa(output):
        # [SALA] Chamado pelo CrewAI depois de cada tarefa aprovada
        if sala.get("etapa") == "descoberta":
            sala.publicar(
                "Funcionalidades aprovadas. Começando as user stories.",
                tipo="ok", estado="escrevendo", etapa="backlog", tentativa=0, motivo="",
            )

    # 5. MONTA O CREW SO COM O PO
    crew = Crew(
        agents=[po_agent],
        tasks=[descoberta_task, backlog_task],
        verbose=True,
        task_callback=ao_concluir_tarefa,  # [SALA]
    )

    print("\nPO trabalhando... aguarde...\n")
    try:
        result = crew.kickoff()
    except Exception as erro:
        # Se o guardrail esgotar as tentativas, o CrewAI levanta excecao
        print(f"\nO PO nao conseguiu gerar um backlog valido: {erro}")
        print("Tente detalhar mais a ideia ou rodar novamente.")
        return

    # 6. SALVA O RESULTADO (as duas etapas, nao so a ultima)
    documento = "\n\n".join(t.raw for t in result.tasks_output)

    os.makedirs("output", exist_ok=True)
    with open("output/backlog_po.md", "w", encoding="utf-8") as f:
        f.write(documento)

    sala.publicar("Backlog salvo em output/backlog_po.md", tipo="ok", estado="pronto", etapa="fim")

    print("\n" + "=" * 60)
    print("PRONTO! Resultado salvo em: output/backlog_po.md")
    print("=" * 60)
    print(documento)
    esperar_enter()

if __name__ == "__main__":
    main()