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
    # Of the BIC instructions, only this brief and the pinned protected contracts reach the model; the Skill files do not.
    if workflow == "bic" and operation == "inspect":
        lines.extend([
            "1. Inspect only the bounded SOURCE packet, decontextualized DONOR vocabulary evidence, and routed source-language grammar evidence; routine INSPECT does not route OL Scripture.",
            "2. SOURCE is the sole content and translation authority. DONOR supplies vocabulary only and must not be reconstructed into verse wording, syntax, propositions, or sequence.",
            "3. Existing TARGET Scripture is not input evidence and is not routed. Use approved memory as evidence.",
            "4. Read any routed semantic packet before forming lexical hypotheses. Exact local matches, SEMDOM classes, seed forms, and indexed senses are retrieval evidence only, never translation authority.",
            "5. In each challenge, keep what the routed evidence shows apart from inference and from unresolved uncertainty.",
            "6. Propose a memory record only for a reusable project decision the routed evidence supports, and cite that evidence in `evidence_refs`. A proposal is never approved memory.",
            "7. Record translation challenges and memory proposals in one governed JSON object. Do not draft TARGET Scripture.",
        ])
    elif workflow == "bic" and operation == "rewrite":
        lines.extend([
            "1. Use the committed INSPECT record, SOURCE, decontextualized DONOR vocabulary evidence, applicable approved memory, routed source and target grammar contracts, and the protected contracts.",
            "2. SOURCE is the sole content authority; DONOR may suggest lexical forms only. Never derive content, propositions, participant structure, syntax, or verse wording from DONOR, and never read an existing TARGET as evidence.",
            "3. Produce one bounded USFM candidate with exact coordinate coverage and protected semantic-marker integrity.",
            "4. Use routed semantic packets and approved memory before generating new lexical alternatives, and compare only semantically viable verbs or constructions.",
            "5. For each challenge, record `risk.before_ol` (0-4) and its material trigger codes. Do not request, read, or simulate original-language evidence: at material semantic-risk level 2 or higher with a material trigger, SAGE runs one automatic bounded OL check for that challenge as a separate single-verse question and merges any better candidate itself. Uncommon or formal wording alone is not a trigger.",
            "6. At risk 3 or 4, still complete the candidate with the recommended rendering, and keep the concise material alternatives considered, each with its rejection code and reason. REWRITE accepts no Operator candidate input.",
            "7. Linguistic uncertainty elevates the report; it does not block completion of the current REWRITE operation.",
            "8. Complete the rule-by-rule grammar assessment and concise translation-challenge report: list material urgency 2–4 items, consolidate repeated causes, and aggregate lower-level or automatically resolved matters.",
        ])
    elif workflow == "bic":
        lines.extend([
            "1. Review only the sealed predecessor rewrite candidate in this fresh task context.",
            "2. Read the routed predecessor material-challenge ledger and verify the completed REWRITE candidate independently. REWRITE has no Operator candidate-selection path.",
            "3. Do not read or reproduce first-pass rationale.",
            "4. Compare the candidate directly with SOURCE, verse by verse, for additions, omissions, semantic shifts, wrong senses, referent errors, grammar that obscures meaning, information-order errors, and altered or missing USFM content.",
            "5. Re-check every verb or construction choice behind a material challenge in the ledger, and resolve, revise, or carry it forward.",
            "6. Correct only supported fidelity, USFM, project-grammar, or governed candidate-decision issues, and return the complete corrected candidate.",
            "7. Complete the rule-by-rule grammar assessment for the final candidate.",
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
