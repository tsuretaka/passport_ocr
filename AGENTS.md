# COLT Engineering Rules — Minimum Necessary Complexity

These instructions apply to AI coding agents working in this repository. The goal is **the simplest maintainable implementation that fully satisfies the current request**. More code, layers, configuration, and dependencies are not evidence of better quality.

## 1. Start with what already exists

- Inspect the relevant implementation, tests, configuration, and project-specific instructions before editing.
- Reuse established functions, components, data models, services, and workflows. Do not build a parallel mechanism for an existing capability.
- Make the smallest coherent change that solves the stated problem. Avoid unrelated refactoring, renaming, migration, file moves, or formatting churn.
- If the requested behavior already works, explain the evidence instead of changing code merely to show activity.

## 2. Do not overengineer

- Prefer straightforward, local code. Keep one-off logic at its call site unless extracting it makes a genuinely complex boundary clearer.
- Do not introduce a helper, class, interface, factory, adapter, hook, abstraction, or generic framework solely for possible future reuse.
- Avoid creating extra state, configuration flags, environment variables, feature toggles, caches, queues, schedulers, or retry systems without a demonstrated present need.
- Do not add packages, services, databases, endpoints, workers, or infrastructure when the existing stack can meet the requirement.
- Validate untrusted input at its actual trust boundary. Do not repeatedly validate internal values already guaranteed by the schema, type, or preceding checks.
- Handle real failure modes explicitly, but avoid blanket `try/catch`, silent fallbacks, excessive defensive branches, and speculative race-condition workarounds.
- Preserve simple control flow. Prefer clear names and readable code over clever compression; fewer lines alone are not the objective.
- Do not duplicate business logic in tests. Test observable behavior with the narrowest meaningful coverage; reuse existing test conventions.

## 3. Complexity requires evidence

Before proposing an additional layer or mechanism, be able to answer:

1. Which current requirement or observed failure makes it necessary?
2. Why can the existing implementation not handle it simply?
3. What maintenance, operational, security, and dependency costs does it add?
4. What is the simpler alternative, and why is that insufficient?

If these answers are not concrete, **do not add the complexity**. Do not silently expand scope to handle hypothetical future needs.

## 4. Keep essential correctness and safety

- Simplicity does not justify weakening authentication, authorization, secrets handling, privacy, data integrity, or required input validation.
- Preserve necessary transaction boundaries, idempotency, and recovery behavior for real external side effects (for example, payments, webhooks, and durable writes).
- Do not remove working safeguards or tests simply to reduce code size. Any simplification must preserve existing behavior and guarantees.
- Generated files and deployment artifacts must be changed through their existing source/build process, not edited as a substitute for the source.

## 5. Changes that require explicit approval

Present the concrete reason and least-complex alternative **before implementing** any unrequested:

- New dependency, external service, platform, database, queue, or long-running process.
- Architectural rewrite, broad refactor, schema migration, or breaking API change.
- New background automation, deployment workflow, access permission, or paid resource.
- Production release, public publication, destructive data operation, or change to secrets/credentials.

Do not turn ordinary small edits into approval requests. When none of these boundaries is crossed, proceed within the authorized task.

## 6. Finish with a concise change report

Report only:

- **Changed:** what was changed and why it meets the request.
- **Not added:** any significant mechanism intentionally avoided, if relevant.
- **Verified:** focused checks actually run and any limitations.

Do not claim tests, deployments, or validations that were not performed. If an existing project instruction imposes a stricter security, testing, or approval requirement, preserve it. Never use this file to override higher-priority instructions.
