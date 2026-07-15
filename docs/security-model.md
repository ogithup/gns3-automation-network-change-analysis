# Security Model

## Deterministic Boundaries

The AI layer may:

- interpret natural-language topology requirements into `TopologySpec`
- interpret natural-language change requests into typed `NetworkChangeCommand`
- explain deterministic validation, simulation, and risk results

The AI layer may not:

- call GNS3 directly
- calculate reachability
- calculate risk
- approve changes
- apply configuration commands
- bypass schema validation

## Prompt-Injection Protections

The Sprint 16 AI service inspects:

- user prompts
- uploaded configuration text
- device names
- descriptions
- discovered CLI output
- any additional AI context payloads

The service sanitizes suspicious context strings and blocks high-severity attempts such as:

- `ignore previous instructions`
- `call GNS3 directly`
- `approve automatically`
- `bypass validation`

## Human-in-the-Loop

Every AI interpretation is returned as a preview object with:

- validated topology or command payload
- warnings
- clarification questions
- safety findings

No AI interpretation is executed automatically.
