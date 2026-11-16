# agents/architect_agent.py
# Agente Arquiteto de Software do Agentic Squad
# Responsavel por decidir a stack e o contrato tecnico do projeto.
#
# O trabalho e dividido em 2 etapas (prompt chaining), igual ao PO e ao SM:
#   1. STACK:    tecnologias e 5 modulos do sistema
#   2. CONTRATO: entidades e endpoints, ligados aos modulos e as tarefas do SM

from crewai import Agent

def create_architect_agent(llm):
    """
    Cria o agente Arquiteto de Software.
    Recebe o LLM configurado no main.py
    """
    return Agent(
        role="Arquiteto de Software Senior",
        goal=(
            "Definir a stack, os modulos e o contrato tecnico (entidades e endpoints) "
            "do produto, para o time de desenvolvimento seguir sem inventar decisoes."
        ),
        backstory=(
            "Voce e um Arquiteto de Software com 10 anos de experiencia em produtos digitais. "
            "Voce escolhe tecnologias simples e coerentes com a ideia, divide o sistema em "
            "poucos modulos com responsabilidade clara e descreve entidades e endpoints "
            "objetivos. "
            "Voce segue formatos pedidos a risca e responde sempre em portugues brasileiro."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

# ETAPA 1: STACK
# Recebe as tarefas do Scrum Master via context.
# Campos e quantidade de modulos fixos: o guardrail confere por codigo.
STACK_PROMPT = """
Voce e o Arquiteto de Software Senior deste projeto.

IDEIA ORIGINAL: {idea}

Voce recebeu as tarefas tecnicas do Scrum Master (T01.1, T01.2, ...).
Sua tarefa agora e escolher a stack e dividir o sistema em EXATAMENTE 5 modulos.

Escolha tecnologias populares e coerentes com a ideia. Nao invente funcionalidades.
Comece direto em STACK, sem frase de introducao.

FORMATO OBRIGATORIO - copie exatamente assim:

STACK
- Linguagem: [uma linguagem]
- Framework: [um framework]
- Banco de dados: [um banco]
- Interface: [web, mobile ou desktop]
- Justificativa: [uma frase]

MODULOS
- M1 | [nome do modulo] | [responsabilidade em ate 8 palavras]
- M2 | [nome do modulo] | [responsabilidade em ate 8 palavras]
- M3 | [nome do modulo] | [responsabilidade em ate 8 palavras]
- M4 | [nome do modulo] | [responsabilidade em ate 8 palavras]
- M5 | [nome do modulo] | [responsabilidade em ate 8 palavras]

REGRAS DE ARQUITETURA - OBRIGATORIAS:
1. Os titulos STACK e MODULOS ficam SOZINHOS em uma linha, sem acento e sem negrito.
2. Escolha UMA tecnologia por linha, nao liste alternativas.
3. Sao exatamente 5 modulos, M1 a M5, com nomes DIFERENTES.
4. Use sempre '-' no inicio da linha e '|' para separar as 3 partes dos modulos.
"""

# ETAPA 2: CONTRATO
# Recebe as tarefas do SM e a stack da etapa 1 via context.
# Cada endpoint aponta um modulo (M1-M5) e os codigos de tarefa que ele cobre:
# e esse vinculo que o Dev usa para saber o que implementar em cada tarefa.
CONTRACT_PROMPT = """
Voce e o Arquiteto de Software Senior deste projeto.

IDEIA ORIGINAL: {idea}

Voce ja definiu a stack e os 5 modulos. Agora descreva o contrato tecnico:
as entidades do sistema e os endpoints, usando os codigos de tarefa do Scrum Master.

Use somente os modulos M1 a M5 da etapa anterior. Nao troque de produto.
Comece direto em ENTIDADES, sem frase de introducao.

FORMATO OBRIGATORIO - copie exatamente assim:

ENTIDADES
- [Entidade]: [campo1], [campo2], [campo3]
- [Entidade]: [campo1], [campo2], [campo3]
- [Entidade]: [campo1], [campo2], [campo3]

ENDPOINTS
- [METODO] /[rota] | M1 | cobre: T01.1, T01.2
- [METODO] /[rota] | M2 | cobre: T02.1

REGRAS DE ARQUITETURA - OBRIGATORIAS:
1. Os titulos ENTIDADES e ENDPOINTS ficam SOZINHOS em uma linha, sem acento e sem negrito.
2. Liste de 3 a 6 entidades, cada uma com pelo menos 3 campos.
3. Liste de 8 a 12 endpoints. METODO so pode ser GET, POST, PUT ou DELETE.
4. Cada endpoint cita 1 modulo (M1 a M5) e 1 ou 2 codigos de tarefa que existem na etapa do Scrum Master.
5. Nao repita o mesmo METODO com a mesma rota.
6. Use sempre '-' no inicio da linha e '|' para separar as partes.
"""