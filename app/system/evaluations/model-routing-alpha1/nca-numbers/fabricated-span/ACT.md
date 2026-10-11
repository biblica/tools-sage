# Sealed model evaluation — nca-numbers — fabricated-span

Use only input.fixture.txt and the registered Skill contract.
Return one JSON object matching the evaluation-result schema.
Preserve task, Skill, case, scope, reviewed-item, and evidence identity exactly.
Do not expand scope, add evidence, write Scripture, combine items, or qualify yourself.
Only target numeric inventory may contain multiple independent inputs in one bounded review item; keep each input ID exact.
Follow the counting convention: one value and one kind per counted number, in reading order. Missing or invalid extraction members stay pending; PARTIAL and UNSUPPORTED remain unresolved evidence without automatic retries.
Use only target text and parsing conventions for extraction. Preserve one exact parent request/response receipt and locally bind accepted members to it.
