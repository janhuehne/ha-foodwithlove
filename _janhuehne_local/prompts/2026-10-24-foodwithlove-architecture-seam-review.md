## Prompt
Adopt Architect Alphonso and perform a read-only adversarial architecture review of foodwithlove v0.3.0, focusing on lifecycle, auth modes, write features, entry cardinality, and unofficial API dependency; cite file and line.

## Context
Static architecture review of a personal Home Assistant custom integration backed by reverse-engineered public, Firebase Auth, and Firestore interfaces.

## Outcome summary
Identified lifecycle ownership, identity, failure-isolation, mutation consistency, feature-contract, and anti-corruption seams that can cause stale state, false-empty state, or remote data drift.

## Reflection note
The sharply named seams and required evidence format made the review focused; next time, include an explicit supported Home Assistant version range and mocked contract tests to validate lifecycle findings dynamically.

## Reusable
yes
