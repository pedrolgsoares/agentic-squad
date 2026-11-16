# agents/po_agent.py
# Agente Product Owner do Agentic Squad
# Responsavel por transformar a ideia em Product Backlog.
#
# O trabalho e dividido em 2 etapas (prompt chaining), porque um modelo
# pequeno como o llama3.2 (3B) se perde em saidas longas de uma vez so:
#   1. DESCOBERTA: visao, personas e 10 funcionalidades distintas e ordenadas
#   2. BACKLOG:    1 user story por funcionalidade + priorizacao + riscos

from crewai import Agent

def create_po_agent(llm):
    """
    Cria o agente Product Owner.
    Recebe o LLM configurado no main.py
    """
    return Agent(
        role="Product Owner Senior",
        goal=(
            "Transformar ideias de clientes em um Product Backlog claro, "
            "priorizado e pronto para desenvolvimento."
        ),
        backstory=(
            "Voce e um Product Owner com 10 anos de experiencia em produtos digitais. "
            "Voce escreve User Stories objetivas, cada uma com criterios de aceite "
            "verificaveis, e prioriza usando MoSCoW. "
            "Voce segue formatos pedidos a risca e responde sempre em portugues brasileiro."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

# ETAPA 1: DESCOBERTA
# A lista sai ORDENADA por importancia: assim a prioridade da etapa 2
# vira regra de posicao, o que um modelo pequeno segue com facilidade.
DISCOVERY_PROMPT = """
IDEIA: {idea}

Produza EXATAMENTE as 3 secoes abaixo, com ESTES TITULOS EXATOS, cada um em uma linha sozinha:

1. VISAO DO PRODUTO
Duas linhas: para quem e, qual problema resolve, qual o diferencial.

2. PERSONAS
Duas personas que USAM o produto final (nao sao desenvolvedores do app).
Formato:
- <Nome>, <idade> anos. Objetivo: <objetivo>. Dor: <dor principal>.
- <Nome>, <idade> anos. Objetivo: <objetivo>. Dor: <dor principal>.
Nao escreva PERFIS, PUBLICO-ALVO ou USUARIOS. O titulo tem que ser exatamente '2. PERSONAS'.

3. FUNCIONALIDADES
Liste 10 funcionalidades DIFERENTES do produto, numeradas de 1 a 10,
uma por linha, com no maximo 8 palavras cada.
Ordene da mais essencial (1) para a menos essencial (10).
Nao repita funcionalidades nem escreva a mesma ideia com outras palavras.
"""

# ETAPA 2: BACKLOG
# Recebe a saida da etapa 1 via context.
# O PO transforma cada funcionalidade da etapa 1 em 1 User Story.
# Sem exemplo de outro dominio: usa placeholder generico para o modelo
# nao copiar conteudo de gastos quando a ideia e de seguranca.
BACKLOG_PROMPT = """
Voce e o Product Owner Senior deste projeto.

Voce ja fez a descoberta na etapa anterior: Visao, Personas e 10 funcionalidades.
Agora, como PO, sua tarefa e transformar CADA funcionalidade em 1 User Story.

IDEIA ORIGINAL: {idea}

Use as 10 funcionalidades da etapa anterior, na mesma ordem.
Nao invente funcionalidades novas. Nao troque de produto.

FORMATO OBRIGATORIO PARA CADA HISTORIA - copie exatamente assim:

[US-01] MUST
Como [tipo de usuario] quero [acao DIFERENTE em cada historia] para [beneficio]
Criterios de Aceite:
- [criterio 1 especifico e testavel]
- [criterio 2 especifico e testavel]
- [criterio 3 especifico e testavel]
Estimativa: M

REGRAS DE PO - OBRIGATORIAS:
1. CADA historia comeca com [US-01] MUST, [US-02] MUST... Nao escreva [Prioridade: MUST], escreva so MUST depois do colchete.
2. TODAS as 10 historias, INCLUSIVE a US-10 WONT, precisam de 3 criterios com '-' no inicio.
3. COPIE ESTA LISTA EXATAMENTE, SEM TROCAR NADA:
   [US-01] MUST
   [US-02] MUST
   [US-03] MUST
   [US-04] MUST
   [US-05] SHOULD
   [US-06] SHOULD
   [US-07] SHOULD
   [US-08] COULD
   [US-09] COULD
   [US-10] WONT
   ATENCAO: US-07 e SHOULD, nao e COULD. US-08 e COULD.
4. NUNCA repita a mesma acao 'quero...'. Cada US tem que ter uma acao diferente: cadastrar, visualizar, filtrar, exportar, compartilhar, alertar, etc.
5. Depois das 10 historias, escreva PRIORIZACAO e depois RISCOS.
6. Nunca use numeros 1. 2. 3. nos criterios. Use sempre '-'.
"""