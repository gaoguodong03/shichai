# 1. Introduction

## 1.1 Background and Motivation

The evolution of autonomous agent systems has undergone a remarkable transformation over the past decade. Early agent architectures relied heavily on hand-crafted rules and explicitly programmed behaviors, offering reliability but limited adaptability. The emergence of reinforcement learning in the 2010s introduced data-driven approaches, enabling agents to learn policies through trial and error. However, these approaches often struggled with generalization across diverse tasks and required extensive training for each new domain.

The advent of large language models (LLMs) in 2022-2023 has fundamentally altered this landscape. Models such as GPT-4, Claude, and LLaMA have demonstrated unprecedented capabilities in natural language understanding, reasoning, and tool use. This has catalyzed the development of LLM-based agents that can interpret complex instructions, decompose tasks, and execute multi-step plans. Central to this new paradigm is the concept of "skills"—modular, reusable capability units that encapsulate specific competencies such as web browsing, code execution, mathematical reasoning, or information retrieval.

The skill-based approach offers several compelling advantages. First, it enables modularity: skills can be developed, tested, and refined independently before being integrated into larger systems. Second, it promotes reusability: a well-defined skill can be deployed across multiple tasks and domains without modification. Third, it facilitates composition: complex tasks can be tackled by orchestrating combinations of simpler skills. Fourth, it supports specialization: different skills can leverage different architectures and optimization strategies tailored to their specific requirements.

Despite these advantages, the current state of research on agent skills remains fragmented. Different research communities have developed diverse representation formalisms, acquisition methods, and composition strategies with little cross-pollination. The reinforcement learning community emphasizes policy representations and skill discovery through intrinsic motivation. The LLM community focuses on prompt-based skill specification and tool integration. The robotics community addresses physical skills and sensorimotor representations. While each approach has merits, the lack of a unified framework hinders progress and makes it difficult to compare methods systematically.

This fragmentation creates several challenges for researchers and practitioners. First, there is no consensus on what constitutes a "skill" or how to formally represent it. Second, skill acquisition methods vary widely and are rarely evaluated on common benchmarks. Third, composition strategies are often task-specific and lack generalizability. Fourth, there are no standardized evaluation protocols for skill-based agents. These challenges motivate the need for a systematic survey that synthesizes advances across communities and identifies research gaps.

## 1.2 Scope and Definitions

### 1.2.1 Agent Definition

In this survey, we define an **agent** as an autonomous system capable of perceiving its environment, reasoning about goals, making decisions, and executing actions to achieve specified objectives. This definition encompasses a broad spectrum of systems, from simple reactive agents to sophisticated multi-agent systems. Key characteristics include:

- **Autonomy**: The ability to operate without continuous human intervention
- **Perception**: The capacity to gather information from the environment through sensors or interfaces
- **Reasoning**: The capability to process information, form hypotheses, and draw inferences
- **Decision-making**: The ability to select actions based on reasoning and goals
- **Action execution**: The capacity to perform actions that affect the environment

Our focus is primarily on agents powered by large language models or related foundation models, as these represent the current frontier of agent capabilities. However, we also draw insights from earlier paradigms including reinforcement learning agents and symbolic AI systems where relevant.

### 1.2.2 Skill Definition

A **skill** is a modular, executable capability unit that enables an agent to perform a specific class of tasks or operations. Skills encapsulate both the knowledge required to perform a task and the procedures for executing it. Key properties of skills include:

- **Modularity**: Skills are self-contained and can be understood and developed independently
- **Reusability**: Skills can be applied across multiple tasks and contexts
- **Composability**: Skills can be combined to perform more complex operations
- **Abstraction**: Skills provide a level of abstraction that hides implementation details
- **Specialization**: Skills are optimized for specific types of tasks or domains

Examples of skills include:
- **Information retrieval**: Querying databases or search engines
- **Code execution**: Running Python code or other programming languages
- **Text analysis**: Summarization, sentiment analysis, or information extraction
- **Tool use**: Interfacing with APIs, web services, or external systems
- **Reasoning**: Logical deduction, mathematical problem-solving, or planning

We distinguish skills from related concepts as follows:

- **Tasks**: A task is a specific problem to be solved (e.g., "find the capital of France"), whereas a skill is the capability to solve a class of tasks (e.g., "information retrieval")
- **Tools**: A tool is a resource or mechanism that can be used (e.g., a search API), whereas a skill is the knowledge and procedures for effectively using that tool
- **Capabilities**: A capability is a general ability (e.g., "reasoning"), whereas a skill is a concrete, implementable unit that realizes that capability

### 1.2.3 Skill-Based Agent Architecture

A **skill-based agent** is an agent whose architecture is organized around a library of skills that can be dynamically selected, composed, and executed to achieve goals. The core components typically include:

- **Skill Library**: A repository of available skills with metadata describing their functionality, inputs, outputs, and constraints
- **Skill Selector**: A mechanism for identifying relevant skills given a current task or context
- **Skill Composer**: A system for combining multiple skills into executable plans
- **Execution Engine**: A runtime environment that executes skills and manages their interactions
- **Learning Module**: Components for acquiring new skills from data, demonstrations, or experience

This architecture enables agents to leverage specialized expertise while maintaining flexibility through skill composition. It also supports continuous learning as new skills can be added to the library without redesigning the entire system.

### 1.2.4 Survey Scope

This survey focuses on research published between 2020 and 2025, with emphasis on the post-LLM period (2023-2025). We prioritize work that addresses skills in the context of autonomous agents, particularly those powered by large language models. However, we also include relevant earlier work that provides foundational concepts or insights.

We organize our analysis around four core dimensions:

1. **Skill Representation**: How skills are formally defined, encoded, and stored
2. **Skill Acquisition**: How agents learn or obtain new skills
3. **Skill Composition**: How multiple skills are combined to perform complex tasks
4. **Skill Evaluation**: How skill quality and agent performance are measured

Within each dimension, we categorize approaches, identify key challenges, and highlight promising directions. We do not attempt to exhaustively survey all related work, but rather to provide a structured overview that captures the main threads of research and their interconnections.

## 1.3 Contributions and Organization

This paper makes three primary contributions:

**First**, we provide a systematic survey of recent advances in agent skills across four dimensions—representation, acquisition, composition, and evaluation. For each dimension, we categorize existing approaches, analyze their strengths and limitations, and identify common patterns. This synthesis brings together work from diverse research communities that have traditionally operated in isolation.

**Second**, we identify five key research gaps that hinder progress in the field: (1) the lack of unified skill representation frameworks, (2) limited interpretability in neural skill representations, (3) insufficient mechanisms for cross-domain skill transfer, (4) the absence of standardized evaluation benchmarks, and (5) challenges in scalable skill library management. These gaps serve as a roadmap for future research.

**Third**, we propose a unified framework for skill-based agents that integrates insights from surveyed approaches. This framework specifies the key components and their interactions, identifies design tradeoffs, and suggests concrete research directions including neuro-symbolic skill representations, meta-learning for skill acquisition, and benchmark development.

The remainder of this paper is organized as follows. Section 2 examines skill representation approaches, including symbolic, neural, and hybrid methods. Section 3 reviews skill acquisition paradigms, covering learning from demonstration, instruction, and reinforcement. Section 4 analyzes skill composition strategies, from sequential planning to dynamic execution. Section 5 discusses evaluation methods and future research directions. Section 6 concludes with a summary and open challenges.