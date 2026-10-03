# Agent Usage

## Overview

This project, the Agentic Data Migration Planner and Reconciliation Workbench, helps plan and validate the migration of one bounded dataset from a source schema to a target schema. AI assistance was used in two ways:

1. **During development.** An AI assistant helped design, implement, test, and document the application.
2. **Inside the application.** A deterministic Mock AI migration-planning agent analyzes the supplied schemas and sample records and proposes a migration plan. It is restricted to inspection and validation.

The deployed application does not call an external LLM provider. A human must approve the migration plan before anything is executed.

## Tools Used

| Tool | Role | AI agent? |
|---|---|---|
| ChatGPT | AI assistant used for development assistance (see Delegated Work) | Yes |
| Python / FastAPI development tools | Backend implementation, local running, and testing | No |
| GitHub Desktop | Version control and repository management | No |
| Render | Hosting and deployment of the application | No |

GitHub Desktop and Render are development and deployment tools. They are not AI agents and made no AI-driven decisions about the project.

## Representative Development Prompts

These are representative paraphrases of the kinds of prompts used. They are not exact historical transcripts.

- **Architecture:** "Design a full-stack application for planning, dry-running, approving, executing, reconciling, and rolling back a migration of one bounded dataset. Separate the API, service layer, AI planning layer, and persistence."
- **Backend/API:** "Implement FastAPI endpoints for projects, schemas, sample records, analysis, plan versions, approval, dry runs, execution, reconciliation, rollback, and history, with Pydantic validation and meaningful HTTP error codes."
- **Frontend integration:** "The frontend keeps migration state in memory. Connect it to the backend APIs so that project, plan, dry-run, execution, and audit state survive a browser refresh."
- **Migration transformations:** "Implement a fixed registry of supported transformations, including multi-field ones, with parameter validation. Do not allow arbitrary user-supplied code."
- **Testing:** "Add unit and integration tests for approval gates, deterministic dry runs, idempotent retries, reconciliation, and rollback isolation, plus a browser end-to-end test of the main workflow."
- **Requirement verification:** "Check the implementation against the requirements and list anything that is missing, simulated, or unverified. Do not claim a feature works unless it was tested."

## Delegated Work

AI assistance was used for:

- Architecture and project scaffolding
- Backend and API implementation
- Frontend-to-API integration
- Implementation of the supported transformations
- Test generation and improvement
- Error handling
- Documentation and deployment configuration
- Requirement verification

## Important Agent Mistakes / Rejected Suggestions

1. **In-memory frontend state replaced.** The initial implementation kept migration state in the frontend, in memory. That was unsuitable for persistent behavior, because state was lost on refresh and the frontend and backend had separate sources of truth. It was replaced with backend API integration and SQLite persistence.
2. **AI execution capabilities rejected.** Giving the AI layer tools to execute migrations, insert target records, modify the target, or roll back was intentionally rejected and blocked. This preserves the human approval requirement.
3. **External LLM integration left out.** A real external LLM provider was considered but intentionally not included in the deployed assessment version. This keeps the workflow reproducible and removes any dependency on external API availability or credentials.

## Verification

The implementation was verified through:

- Unit and integration tests
- Browser end-to-end tests
- Frontend/API integration testing
- SQLite persistence testing
- Migration plan versioning checks
- Human approval gate checks
- Deterministic dry-run checks
- Quarantine of invalid records
- Duplicate prevention and idempotent retry checks
- Source/target reconciliation checks
- Rollback checks
- Audit/history verification
- Verification of the hosted deployment

Exact test counts are not stated here because they were not part of the information used to prepare this document.

## AI Safety Boundary

The AI/planning layer is limited to:

- Inspection
- Validation
- Schema analysis
- Mapping proposals
- Transformation suggestions
- Risk identification
- Clarification questions
- Migration plan preparation

The AI has no tools to execute migrations, insert records into the target, modify the target database, or perform rollback. Execution is performed by the application only after a human explicitly approves the migration plan. The AI can only propose a plan. It cannot approve one.

Transformations are limited to 12 predefined, supported transformations, and the sample size is capped at 50. Arbitrary transformation code is not executed.

## Limitations

- The deployed AI workflow is a deterministic Mock AI agent, not a live external LLM integration.
- There is no production-grade external LLM provider in the deployed assessment version.
- There is no production database connector.
- There are no live cloud data connectors.
- There is no distributed migration.
- There is no arbitrary transformation code execution.
- There is no authentication system.
