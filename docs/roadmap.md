# Roadmap

## 0.12: correctness and complete local workflows

Implemented: reviewed correctness fixes, shared VR/backend semantics, safe audits,
atomic files, collection checks, keyed releases and resume, JSON CLI, packaging
and Python 3.9–3.14 validation. See migration-0.12.md and conformance.md.

## Next: adoption evidence

- Expand independent vendor/character-set and malformed-input fixtures.
- Benchmark end-to-end memory, throughput and interrupted-job recovery.
- Validate real Orthanc/dcm4chee deployments and publish their exact support matrix.
- Add enhanced/per-frame geometry and derived-object integration through highdicom.
- Publish searchable versioned API documentation and user-tested migration recipes.
- Pilot commercial workflows with explicit support and security response ownership.

## 1.0 gate

Stabilize the declared workflow scope, verify artifacts and migrations, publish
validation evidence, and establish a support/deprecation policy. Do not equate
1.0 with implementing every codec, IOD, confidentiality option, or a new DIMSE stack.
