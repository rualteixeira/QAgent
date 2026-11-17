"""Partes do executor LLM de um passo.

- errors      — exceções do passo (intervenção humana, estado pré-existente, uso incorreto de ferramenta)
- schemas     — argumentos das ferramentas e do veredicto (as descrições vão para o LLM: têm de ser genéricas)
- device      — vista do dispositivo: ecrã atual, refs → elementos, gestos e teclas
- recording   — registo das ações/locators no StepResult e máscara de segredos
- navigation  — apps instaladas e abertura de apps (arranque a frio na 1.ª vez)
- state       — estado por passo (contadores e contestações)
- tools       — as ferramentas expostas ao LLM
- verdict     — regras do veredicto (finish_step) e asserções estruturadas
- transcript  — mensagens para o LLM e compactação de ecrãs antigos
O ciclo ReAct (AiStepExecutor) continua em qagent.ai_executor.
"""
