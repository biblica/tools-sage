"""ACT.md rendering: the per-operation process brief.

Split from act_tasks.py.
"""

from __future__ import annotations

from typing import Any, Mapping

from .ol_referrals import is_ol_referral_contract


def process_brief_lines(
    *,
    workflow: str,
    operation: str,
    rtc_stage: str | None,
    rtc_policy: Mapping[str, Any] | None,
    ol_referral_contract: str | None,
    output_project_id: str,
    source_project_id: str,
) -> list[str]:
    """Return the numbered process-brief steps for one workflow operation or RTC stage."""
    # ACT rendering maintenance boundary: these steps are sealed into ACT.md, whose hash the control record
    # checks at submission; keep the step numbering contiguous within each branch.
    lines: list[str] = []
    if workflow == "bic" and operation == "inspect":
        lines.extend([
            "1. Inspect only the bounded SOURCE packet, decontextualized DONOR vocabulary evidence, and routed source-language grammar evidence; routine INSPECT does not route OL Scripture.",
            "2. SOURCE is the sole content and translation authority. DONOR supplies vocabulary only and must not be reconstructed into verse wording, syntax, propositions, or sequence.",
            "3. Existing TARGET Scripture is not input evidence and is not routed. Use approved memory as evidence; propose additions but never approve them.",
            "4. Record translation challenges and memory proposals in one governed JSON object. Do not draft TARGET Scripture.",
        ])
    elif workflow == "bic" and operation == "rewrite":
        lines.extend([
            "1. Use the committed INSPECT record, SOURCE, decontextualized DONOR vocabulary evidence, applicable approved memory, routed source and target grammar contracts, and protected rewrite rules; do not open conditional OL files during ordinary drafting.",
            "2. SOURCE is the sole content authority; DONOR may suggest lexical forms only. Never derive content, propositions, participant structure, syntax, or verse wording from DONOR, and never read an existing TARGET as evidence.",
            "3. Produce one bounded USFM candidate with exact coordinate coverage and protected semantic-marker integrity.",
            "4. Preserve source content and genuine ambiguity; do not add, omit, harmonise, or doctrinally clarify.",
            "5. Score candidate lexical burden on the governed 0-4 rubric; use Longman bands only when licensed evidence is routed and never invent a band.",
            "6. At material semantic-risk level 2 or higher, run one automatic bounded OL check per material challenge when a trigger exists: it is question-specific, and raw SOURCE and OL Scripture are restricted to that challenge's single verse. For VERB_CHOICE resolve only the disputed verb's verbal sense/function. Do not route OL merely because a verb is uncommon.",
            "7. If bounded OL evidence supports a better candidate, update the USFM candidate, recheck grammar, and report the before/after risk and candidate change.",
            "8. If post-OL risk remains level 3 or 4, complete REWRITE with the recommended candidate, retain concise material alternatives and rejection reasons, and elevate the risk-rated report; REWRITE accepts no Operator candidate input.",
            "9. Linguistic uncertainty elevates the report; it does not block completion of the current REWRITE operation.",
            "10. Complete the rule-by-rule grammar assessment and concise translation-challenge report: list material urgency 2–4 items, consolidate repeated causes, and aggregate lower-level or automatically resolved matters.",
        ])
    elif workflow == "bic":
        lines.extend([
            "1. Review only the sealed predecessor rewrite candidate in this fresh task context.",
            "2. Read the routed predecessor material-challenge ledger and verify the completed REWRITE candidate independently. REWRITE has no Operator candidate-selection path.",
            "3. Do not read or reproduce first-pass rationale.",
            "4. Correct only supported fidelity, USFM, project-grammar, or governed candidate-decision issues.",
            "5. Complete the rule-by-rule grammar assessment for the final candidate.",
        ])
    elif operation == "rtc":
        lines.append(f"Composite RTC stage: `{rtc_stage}`.")
        if rtc_stage == "STRUCTURAL_ADJUDICATION":
            lines.extend([
                "1. Adjudicate only the supplied deterministic structural candidates.",
                "2. Do not perform the translation-and-meaning review in this stage.",
                "3. VRS mappings and coordinate differences are report-only structural evidence: they never block RTC or make a review portion indivisible. Ordinary mappings are not findings unless the bounded evidence proves a real structural difference.",
                "4. Do not request or use original-language Scripture in this stage.",
            ])
        elif rtc_stage == "REFERENCE_TEXT_COMPARISON":
            drift_enabled = str(
                dict((rtc_policy or {}).get("original_language") or {}).get(
                    "source_text_drift_adjudication", "PROHIBITED"
                )
            ).upper() == "ENABLED"
            if not drift_enabled:
                referral_instruction = (
                    "7. Source-text drift adjudication is PROHIBITED. Do not emit "
                    "ol_review_requests; assess only from the authorized non-OL evidence "
                    "routed to this stage."
                )
            elif is_ol_referral_contract(ol_referral_contract):
                referral_instruction = (
                    "7. Automatic WIP-Reference source adjudication is ENABLED under "
                    f"{ol_referral_contract}. Emit an ol_review_requests entry if and "
                    "only if every admission rule passes: (1) the difference changes the "
                    "core proposition; (2) WIP and REFERENCE communicate incompatible "
                    "meanings; (3) conflict_class is exactly one of "
                    "NEGATION_OR_POLARITY_CONFLICT, "
                    "PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT, "
                    "CORE_EVENT_OR_STATE_CONFLICT, or "
                    "CORE_PROPOSITION_OMISSION_OR_ADDITION; (4) correctness genuinely "
                    "requires the applicable original-language text; (5) routed non-OL "
                    "evidence cannot settle the issue; (6) the request contains one issue "
                    "at the smallest necessary Scripture scope; and (7) the same normalized "
                    "conflict is not requested twice. Do not refer lexical nuance or "
                    "intensity, style, register, readability, grammar, spelling, punctuation, "
                    "USFM structure, ordinary consistency, equivalent paraphrase, or any "
                    "issue resolvable from routed non-OL evidence. Do not finalize the same "
                    "issue as an RTC finding. SAGE routes OT requests to the Job-bound Hebrew "
                    "resource and NT requests to the Job-bound Greek resource."
                )
            else:
                referral_instruction = (
                    f"7. Automatic WIP-Reference source adjudication is ENABLED. Defer every "
                    f"material content-bearing variance where choosing between "
                    f"{output_project_id} and {source_project_id} depends on the source text. "
                    "Emit one bounded ol_review_requests entry per variance and do not "
                    "finalize that same issue in this stage. SAGE routes OT requests to the "
                    "Job-bound Hebrew resource and NT requests to the Job-bound Greek "
                    "resource. Grammar, readability, punctuation, spelling, USFM/structure, "
                    "style, and ordinary consistency defects remain direct RTC findings and "
                    "must not be routed to OL."
                )
            lines.extend([
                "1. Perform only the RTC checks enabled in the sealed rtc_policy across every bounded primary coordinate in this work unit.",
                "2. SAGE has already formed and bounded this work unit deterministically. Do not re-plan, split, merge, or certify its mechanical boundaries.",
                f"3. Use {source_project_id} as the authorized Reference Project, the {output_project_id} grammar contract, local semantic evidence, any routed structural-stage result, and the explicitly labeled boundary context when present.",
                "4. Context-only coordinates may inform interpretation but must not appear in ordinary findings or OL requests.",
                "5. Treat each WIP or Reference verse bridge as one indivisible record while reviewing every coordinate it covers. Check bridge mapping under structure/completeness and check the complete bridged text against all corresponding WIP and Reference content under translation/meaning, whether their bridge shapes match or differ.",
                "6. Do not read original-language Scripture in this stage.",
                referral_instruction,
                "8. Review every WIP and Reference cross-reference span (`\\x ... \\x*`) under the sealed x-context policy. At minimum verify balanced containers and valid field structure. In NORMAL mode also compare presence, payload, and ordering; report missing, malformed, unexpected, or materially mismatched cross-references at the owning WIP coordinate. SAGE compares Scripture target numbers and footnote origin and text in code.",
                "9. SAGE already reports the routed preflight `direct_findings` (WIP/REFERENCE text gaps); do not restate them. For each preflight `marker_candidates` entry, decide whether the differing `\\add` or `\\nd` usage is material and report only material differences.",
                "10. Numbers: the preflight `numeric_candidates` compares WIP digits with the number index. Report no number finding for a `MATCH` verse; check `DIFFERS` and `NOT_IN_DIGITS` verses against the Reference. The NCA tool checks numbers in full.",
            ])
        else:
            lines.extend([
                "1. Automatically adjudicate exactly the material WIP-Reference variance requests inherited from the meaning stage.",
                f"2. Compare {output_project_id} and {source_project_id} with the testament-correct Job-bound Hebrew (OT) or Greek (NT) packet.",
                "3. Decide which rendering is closer to the routed source, whether both are defensible, or whether the evidence is inconclusive. Do not broaden this internal adjudication into the separate detailed Original-Language Review operation or into grammar, structure, style, consistency, or general RTC.",
                "4. Return exactly one structured ol_resolutions object per inherited request. A FINDING outcome must use that request's deferred_finding_id, cite actual routed OL evidence, and explain the source-text basis for the adjudication. List the original-language words the decision depends on in `ol_words`, with their lemma and parse; SAGE checks each against MACULA.",
                f"5. Set `decision` to exactly one of WIP_CLOSER_TO_SOURCE ({output_project_id} is closer to the source), REFERENCE_CLOSER_TO_SOURCE ({source_project_id} is closer), BOTH_DEFENSIBLE, or INCONCLUSIVE, consistent with `outcome`: FINDING goes with REFERENCE_CLOSER_TO_SOURCE (or INCONCLUSIVE), NO_FINDING with WIP_CLOSER_TO_SOURCE or BOTH_DEFENSIBLE, and INSUFFICIENT_EVIDENCE with INCONCLUSIVE. In `rationale`, name the Projects as {output_project_id} and {source_project_id}, not by role labels.",
            ])
    elif operation == "focused":
        lines.extend([
            "1. Answer the one focus question only, using the routed evidence and check type.",
            "2. Do not broaden into Reference Text Comparison (RTC).",
            "3. Semantically review every assigned primary coordinate and structural candidate; SAGE owns mechanical coverage and receipts.",
        ])
    else:
        lines.extend([
            f"1. Compare {output_project_id} directly with the relevant authoritative OL packet for the one question.",
            f"2. Use {source_project_id} as the authorized Reference Project.",
            "3. Do not broaden into commentary or a general book study.",
            "4. Semantically review every assigned primary coordinate and structural candidate; SAGE owns mechanical coverage and receipts.",
        ])
    return lines
