# Agent Policy for QDistSAT

## Objective
Minimize PI attention while preserving scientific correctness of QLDPC distance encodings and benchmark interpretation.

## Source of truth
- Repository code and tests.
- README.md and docs/REPO_SCOPE.md for supported behavior.
- GitHub issues/PRs for task-specific requirements.
- The research-hub policy in guluchen/ai-research-hub for general escalation rules.

## Autonomous work
Agents should independently handle routine implementation, refactoring, dependencies, test failures, CI failures, benchmark plumbing, documentation, and formatting.

Every substantive change must include appropriate validation. Prefer existing unit/regression tests; add focused tests for bug fixes or semantic changes.

## Scientific boundaries
Do not silently change:
- the definition of code distance or Pauli weight;
- CSS/stabilizer/logical semantics;
- SAT/MaxSAT/SMT encoding meaning;
- benchmark ground truth or expected distances;
- timeout/result interpretation;
- solver-comparison methodology.

If a task appears to require one of these, escalate before changing it.

## Escalate only when
- the scientific specification is ambiguous;
- reasonable alternatives change a scientific conclusion;
- correctness cannot be established after reasonable investigation;
- an unexpected result may be scientifically meaningful;
- a destructive, security-sensitive, irreversible, or unusually expensive action is required.

Do not escalate ordinary engineering failures unless they reveal one of the above.

## Routine PR policy
Routine PRs that satisfy their stated validation criteria may be merged autonomously. Do not require the PI to click merge for routine changes.

## Completion report
- What changed
- Validation performed
- Results, if applicable
- Unresolved issues
- PI action required: yes/no
