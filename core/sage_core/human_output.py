"""Localise human-facing reports and emit readable operational log events.

Machine records remain canonical and language-neutral. This module renders only
human-facing labels and messages according to the two independently configured
channels: operational logs/reports and translation challenges.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from .config import require_mapping, require_string
from .errors import ConfigurationError
from .language_codes import canonical_language_tag

_LANGUAGE_ALIASES = {
    "OPERATOR_LANGUAGE",
    "SOURCE_LANGUAGE",
    "TARGET_LANGUAGE",
    "REFERENCE_LANGUAGE",
}
_VERBOSITY = {"quiet", "normal", "verbose", "debug"}
_SEVERITY_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "NOTICE": 25,
    "SUCCESS": 30,
    "WARNING": 40,
    "CRITICAL": 50,
    "ERROR": 60,
}
_MODE_THRESHOLD = {
    "quiet": 30,
    "normal": 20,
    "verbose": 10,
    "debug": 0,
}


@dataclass(frozen=True)
class OutputLanguageChannel:
    """Language and display settings for one human-output channel."""

    primary_language: str
    secondary_language: str | None
    bilingual: bool

    def tokens(self) -> tuple[str, ...]:
        """Return configured language tokens in display order without duplicates."""
        values = [self.primary_language]
        if self.bilingual and self.secondary_language and self.secondary_language != self.primary_language:
            values.append(self.secondary_language)
        return tuple(values)


@dataclass(frozen=True)
class TranslationChallengeChannel(OutputLanguageChannel):
    """Language and materiality controls for translation-challenge reports."""

    minimum_individual_urgency: int
    aggregate_lower_levels: bool
    consolidate_repeated_cause: bool
    render_only_material_fields: bool


@dataclass(frozen=True)
class HumanOutputSpec:
    """Independent human-output policies plus canonical machine-record controls."""

    operator_language: str
    logs_and_reports: OutputLanguageChannel
    translation_challenges: TranslationChallengeChannel
    machine_language: str
    localise_codes: bool
    verbosity: str


_CATALOGUE: dict[str, dict[str, str]] = {
    "en": {
        "event.COMMAND_STARTED": "Command started",
        "event.REWRITE_STARTED": "REWRITE started",
        "event.REWRITE_COMPLETED": "REWRITE completed",
        "event.CHALLENGE_RECORDED": "Translation challenge recorded",
        "event.OL_CHECK_COMPLETED": "Bounded OL risk check completed",
        "event.SELF_CHECK_AVAILABLE": "SELF-CHECK available",
        "event.INIT_STARTED": "INIT started",
        "event.INIT_COMPLETED": "INIT completed",
        "event.VALIDATION_COMPLETED": "Validation completed",
        "event.COMMAND_COMPLETED": "Command completed",
        "event.COMMAND_FAILED": "Command failed",
        "event.CORRECTION_APPLIED": "Input correction applied",
        "event.REPORT_WRITTEN": "Report written",
        "event.TASK_CREATED": "ACT task created",
        "event.TASK_SUBMITTED": "ACT task submitted",
        "event.STATE_RESET": "Project state reset",
        "event.OL_SUPPLEMENT_AVAILABLE": "Conditional OL evidence available",
        "label.translation_challenges": "BIC Translation Challenges",
        "label.task": "Task",
        "label.operation": "Operation",
        "label.scope": "Scope",
        "label.status": "Status",
        "label.highest_urgency": "Highest urgency",
        "label.material_challenges": "Material challenges",
        "label.minor_aggregated": "Minor matters aggregated",
        "label.no_material_challenges": "No material translation challenges were reported.",
        "label.category": "Category",
        "label.urgency": "Urgency",
        "label.selected": "Selected",
        "label.alternative": "Alternative",
        "label.risk": "Risk",
        "label.evidence": "Evidence",
        "label.action": "Action",
        "label.resolved_by_self_check": "Resolved by SELF-CHECK",
        "label.automatic_resolutions": "Automatic resolutions",
        "label.summary": "Summary",
        "label.report_languages": "Report languages",
        "urgency.0": "Information",
        "urgency.1": "Advisory",
        "urgency.2": "Review recommended",
        "urgency.3": "Urgent",
        "urgency.4": "Critical",
        "report.ecosystem_initialisation": "SAGE ecosystem initialisation report",
        "report.project_init": "SAGE Project INIT report",
        "report.input_remediation": "SAGE input remediation",
        "report.act_work_unit_plan": "SAGE ACT work-unit plan",
        "report.act_task": "SAGE ACT task",
        "report.act_aggregate": "SAGE ACT aggregate",
        "report.bic_memory_review_provenance": "SAGE BIC memory-review provenance",
        "report.project_state_reset": "SAGE project state reset",
        "report.evaluation_queue": "SAGE evaluation queue",
        "report.initialisation_result": "SAGE initialisation result",
        "report.validation_result": "SAGE validation result",
        "report.status_summary": "SAGE status",
        "report.project_registry": "SAGE Project Inventory",
        "report.workflow_status": "Workflow status",
        "report.work_unit_plan": "SAGE work-unit plan",
        "report.transaction_recovery": "SAGE transaction recovery",
        "report.transactions": "Transactions",
        "report.target_generations": "SAGE target generations",
        "report.generation_publication": "SAGE target-generation publication",
        "report.generation_verification": "SAGE target-generation verification",
        "report.doctor": "SAGE doctor",
        "report.request_interpretation": "SAGE request interpretation",
        "report.related_operations": "Related supported operations",
        "report.related_commands": "Related registered commands",
        "report.command_explanation": "SAGE command explanation",
        "report.error": "SAGE error",
        "label.plan": "Plan",
        "label.requested_scope": "Requested scope",
        "label.work_units": "Work units",
        "label.plan_file": "Plan file",
        "label.output_project": "Output project",
        "label.contemporary_source": "Contemporary source",
        "label.focus": "Focus",
        "label.act_prompt": "ACT prompt",
        "label.decision": "Decision",
        "label.review_id": "Review ID",
        "label.removed_entries": "Removed entries",
        "label.set": "Set",
        "label.mode": "Mode",
        "label.queue": "Queue",
        "label.errors": "Errors",
        "label.restrictions": "Restrictions",
        "label.auto_settings": "Auto settings",
        "label.report": "Report",
        "label.auto_report": "Auto report",
        "label.next": "Next",
        "label.runtime": "Runtime",
        "label.execution_available": "Execution available",
        "label.primary_coordinates": "Primary coordinates",
        "label.largest_estimated_tokens": "Largest estimated packet tokens",
        "label.largest_serialized_bytes": "Largest serialised packet bytes",
        "label.manifest": "Manifest",
        "label.transaction": "Transaction",
        "label.pending": "Pending",
        "label.generation": "Generation",
        "label.publication_basis": "Publication basis",
        "label.reused": "Reused",
        "label.path": "Path",
        "label.consumer": "Consumer",
        "label.state_file": "State file",
        "label.verification": "Verification",
        "label.project_snapshot": "Project snapshot",
        "label.integrity_status": "Integrity status",
        "label.python": "Python",
        "label.pyyaml": "PyYAML",
        "label.settings_path": "Settings",
        "label.request": "Request",
        "label.result": "Result",
        "label.read_only_command": "Read-only command",
        "label.changes_runtime_state": "Changes SAGE runtime state",
        "label.details": "Details",
        "label.reason_code": "Reason code",
        "label.message": "Message",
        "label.affected_scope": "Affected scope",
        "label.suggested_alternative": "Suggested alternative",
        "message.projects_preserved": "Projects and configuration were preserved.",
        "message.controls_still_apply": "All normal SAGE parsing, INIT, scope, grammar, review-attention, transaction, and write controls still apply.",
        "message.no_safe_command": "No command is safe to recommend for execution.",
        "message.advisory_only": "Advisory-only mode selected. No project command was executed.",
        "message.interrupted": "Interrupted by Operator.",
        "label.project": "Project",
        "label.language_profile": "Language/profile",
        "label.state": "State",
        "label.roles": "Roles",
        "label.observed_books": "Observed books",
        "label.review": "Review",
        "label.workflow": "Workflow",
        "label.qualification": "Qualification",
        "label.resources": "Resources",
        "label.execution": "Execution",
        "label.capability": "Capability",
        "label.effective_configured": "Effective configured",
        "label.reviewed_coordinates": "Reviewed coordinates",
        "label.findings": "Findings",
        "label.aggregate": "Aggregate",
        "label.target_generation_basis": "Target generation basis",
        "label.language_contracts": "Language contracts",
        "label.pending_transactions": "Pending transactions",
        "label.files": "Files",
        "label.books": "Books",
        "label.verse_units": "Verse units",
        "label.sections": "Sections",
        "label.paragraphs": "Paragraphs",
        "label.setting": "Setting",
        "label.resolved": "Resolved",
        "label.confidence": "Confidence",
        "label.original": "Original",
        "label.effective_value": "Effective value",
        "label.method": "Method",
        "label.source_settings_sha256": "Source settings SHA-256",
        "label.confirmed_resolutions": "Confirmed resolutions",
        "report.init_preserves_source": "INIT preserves the source settings file. Confirmed corrections are written to a governed effective-configuration sidecar and revalidated before use.",
        "report.confirm_project_fields": "Confirm enabled state, language/profile routing, content state, scope, roles, and VRS authority. No correction is applied silently.",
        "report.guided_init_next": "Use guided INIT to correct recoverable settings in the governed sidecar, or edit the source YAML deliberately and rerun INIT. Source edits invalidate stale sidecars.",
        "label.version": "Version",
        "label.projects_root": "Projects root",
        "label.effective_overrides": "Effective overrides",
        "label.workflows": "Workflows",
        "label.projects": "Projects",
        "label.auto_resolved_settings": "Auto-resolved settings",
        "label.operator_resolution_history": "Operator resolution history",
        "label.restrictions_errors": "Restrictions and errors",
        "label.next_action": "Next action",
        "label.settings": "Settings",
        "label.interactive_review": "Interactive review",
        "label.effective_configuration": "Effective configuration",
        "label.unregistered_project_folders": "Project folders not yet in SAGE",
        "label.auto_resolution_review": "Auto-resolution review",
        "label.operator_confirmed_fields": "Operator-confirmed fields",
        "label.yes": "YES",
        "label.no": "NO",
        "label.none": "None",
        "label.no_auto_settings": "No auto settings",
        "label.no_operator_corrections": "No Operator corrections",
        "label.no_unregistered_projects": "No Project folders remain outside SAGE",
        "label.canonical_fallback": "Unlocalised source messages are shown canonically.",
        "report.auto_resolution": "SAGE auto-resolution report",
        "report.auto_resolution_intro": "Every setting declared as `auto` is listed here. SAGE does not rewrite the source YAML.",
        "report.auto_resolution_edit": "Operators may replace any `auto` value with an explicit value and rerun initialisation.",
        "label.resolved_value": "Resolved value",
        "label.source": "Source",
        "label.override": "Override",
        "label.impact_notes": "Impact notes",
        "report.act_submission": "SAGE ACT submission",
        "label.challenge_report": "Challenge report",
        "prompt.value_not_recognised": "{label} {received} was not recognised.",
        "prompt.value_required": "{label} is required.",
        "prompt.possible_corrections": "Possible corrections:",
        "prompt.confidence": "confidence",
        "prompt.enter_another_value": "Enter another value",
        "prompt.cancel": "Cancel",
        "prompt.selection": "Selection: ",
        "prompt.enter_listed_number": "Enter one listed number.",
        "prompt.enter_value": "Enter {label}: ",
        "prompt.resolved_value": "Resolved {label}: {original} -> {corrected}",
        "prompt.use_correction": "Use this correction? [Y/n/edit] ",
        "prompt.configured_false": "The ecosystem is declared configured: false.",
        "prompt.configured_override": "INIT can mark the effective configuration configured without rewriting ecosystem.yml.",
        "prompt.auto_setting": "Auto setting",
        "prompt.proposed_value": "Proposed value",
        "prompt.basis": "Basis",
        "prompt.no_change": "No change recorded.",
        "prompt.project_disabled": "Project {project_id} is in SAGE but disabled in the effective configuration.",
        "fallback.unavailable": "Secondary wording unavailable; canonical wording shown.",
    },
    "id": {
        "event.COMMAND_STARTED": "Perintah dimulai",
        "event.REWRITE_STARTED": "REWRITE dimulai",
        "event.REWRITE_COMPLETED": "REWRITE selesai",
        "event.CHALLENGE_RECORDED": "Tantangan terjemahan dicatat",
        "event.OL_CHECK_COMPLETED": "Pemeriksaan risiko OL terbatas selesai",
        "event.SELF_CHECK_AVAILABLE": "SELF-CHECK tersedia",
        "event.INIT_STARTED": "INIT dimulai",
        "event.INIT_COMPLETED": "INIT selesai",
        "event.VALIDATION_COMPLETED": "Validasi selesai",
        "event.COMMAND_COMPLETED": "Perintah selesai",
        "event.COMMAND_FAILED": "Perintah gagal",
        "event.CORRECTION_APPLIED": "Koreksi masukan diterapkan",
        "event.REPORT_WRITTEN": "Laporan ditulis",
        "event.TASK_CREATED": "Tugas ACT dibuat",
        "event.TASK_SUBMITTED": "Tugas ACT dikirim",
        "event.STATE_RESET": "Status proyek diatur ulang",
        "event.OL_SUPPLEMENT_AVAILABLE": "Bukti OL bersyarat tersedia",
        "label.translation_challenges": "Tantangan Terjemahan BIC",
        "label.task": "Tugas",
        "label.operation": "Operasi",
        "label.scope": "Cakupan",
        "label.status": "Status",
        "label.highest_urgency": "Urgensi tertinggi",
        "label.material_challenges": "Tantangan material",
        "label.minor_aggregated": "Hal minor digabungkan",
        "label.no_material_challenges": "Tidak ada tantangan terjemahan material yang dilaporkan.",
        "label.category": "Kategori",
        "label.urgency": "Urgensi",
        "label.selected": "Pilihan",
        "label.alternative": "Alternatif",
        "label.risk": "Risiko",
        "label.evidence": "Bukti",
        "label.action": "Tindakan",
        "label.resolved_by_self_check": "Diselesaikan oleh SELF-CHECK",
        "label.automatic_resolutions": "Penyelesaian otomatis",
        "label.summary": "Ringkasan",
        "label.report_languages": "Bahasa laporan",
        "urgency.0": "Informasi",
        "urgency.1": "Saran",
        "urgency.2": "Peninjauan dianjurkan",
        "urgency.3": "Mendesak",
        "urgency.4": "Kritis",
        "report.ecosystem_initialisation": "Laporan inisialisasi ekosistem SAGE",
        "report.project_init": "Laporan INIT Proyek SAGE",
        "report.input_remediation": "Remediasi masukan SAGE",
        "report.act_work_unit_plan": "Rencana unit kerja ACT SAGE",
        "report.act_task": "Tugas ACT SAGE",
        "report.act_aggregate": "Agregat ACT SAGE",
        "report.bic_memory_review_provenance": "Provenans peninjauan memori BIC SAGE",
        "report.project_state_reset": "Pengaturan ulang status proyek SAGE",
        "report.evaluation_queue": "Antrean evaluasi SAGE",
        "report.initialisation_result": "Hasil inisialisasi SAGE",
        "report.validation_result": "Hasil validasi SAGE",
        "report.status_summary": "Status SAGE",
        "report.project_registry": "Registri proyek SAGE",
        "report.workflow_status": "Status alur kerja",
        "report.work_unit_plan": "Rencana unit kerja SAGE",
        "report.transaction_recovery": "Pemulihan transaksi SAGE",
        "report.transactions": "Transaksi",
        "report.target_generations": "Generasi target SAGE",
        "report.generation_publication": "Publikasi generasi target SAGE",
        "report.generation_verification": "Verifikasi generasi target SAGE",
        "report.doctor": "Diagnostik SAGE",
        "report.request_interpretation": "Interpretasi permintaan SAGE",
        "report.related_operations": "Operasi terkait yang didukung",
        "report.related_commands": "Perintah terdaftar terkait",
        "report.command_explanation": "Penjelasan perintah SAGE",
        "report.error": "Kesalahan SAGE",
        "label.plan": "Rencana",
        "label.requested_scope": "Cakupan yang diminta",
        "label.work_units": "Unit kerja",
        "label.plan_file": "Berkas rencana",
        "label.output_project": "Proyek keluaran",
        "label.contemporary_source": "Sumber kontemporer",
        "label.focus": "Fokus",
        "label.act_prompt": "Prompt ACT",
        "label.decision": "Keputusan",
        "label.review_id": "ID peninjauan",
        "label.removed_entries": "Entri yang dihapus",
        "label.set": "Set",
        "label.mode": "Mode",
        "label.queue": "Antrean",
        "label.errors": "Kesalahan",
        "label.restrictions": "Pembatasan",
        "label.auto_settings": "Pengaturan otomatis",
        "label.report": "Laporan",
        "label.auto_report": "Laporan otomatis",
        "label.next": "Berikutnya",
        "label.runtime": "Runtime",
        "label.execution_available": "Eksekusi tersedia",
        "label.primary_coordinates": "Koordinat utama",
        "label.largest_estimated_tokens": "Token paket perkiraan terbesar",
        "label.largest_serialized_bytes": "Byte paket terserialisasi terbesar",
        "label.manifest": "Manifes",
        "label.transaction": "Transaksi",
        "label.pending": "Tertunda",
        "label.generation": "Generasi",
        "label.publication_basis": "Dasar publikasi",
        "label.reused": "Digunakan kembali",
        "label.path": "Jalur",
        "label.consumer": "Konsumen",
        "label.state_file": "Berkas status",
        "label.verification": "Verifikasi",
        "label.project_snapshot": "Snapshot proyek",
        "label.integrity_status": "Status integritas",
        "label.python": "Python",
        "label.pyyaml": "PyYAML",
        "label.settings_path": "Pengaturan",
        "label.request": "Permintaan",
        "label.result": "Hasil",
        "label.read_only_command": "Perintah hanya-baca",
        "label.changes_runtime_state": "Mengubah status runtime SAGE",
        "label.details": "Rincian",
        "label.reason_code": "Kode alasan",
        "label.message": "Pesan",
        "label.affected_scope": "Cakupan terdampak",
        "label.suggested_alternative": "Alternatif yang disarankan",
        "message.projects_preserved": "Proyek dan konfigurasi dipertahankan.",
        "message.controls_still_apply": "Semua kontrol normal SAGE untuk parsing, INIT, cakupan, tata bahasa, perhatian peninjauan, transaksi, dan penulisan tetap berlaku.",
        "message.no_safe_command": "Tidak ada perintah yang aman untuk dianjurkan bagi eksekusi.",
        "message.advisory_only": "Mode saran-saja dipilih. Tidak ada perintah proyek yang dijalankan.",
        "message.interrupted": "Dihentikan oleh Operator.",
        "label.project": "Proyek",
        "label.language_profile": "Bahasa/profil",
        "label.state": "Status",
        "label.roles": "Peran",
        "label.observed_books": "Kitab teramati",
        "label.review": "Peninjauan",
        "label.workflow": "Alur kerja",
        "label.qualification": "Kualifikasi",
        "label.resources": "Sumber daya",
        "label.execution": "Eksekusi",
        "label.capability": "Kapabilitas",
        "label.effective_configured": "Konfigurasi efektif",
        "label.reviewed_coordinates": "Koordinat yang ditinjau",
        "label.findings": "Temuan",
        "label.aggregate": "Agregat",
        "label.target_generation_basis": "Dasar generasi target",
        "label.language_contracts": "Kontrak bahasa",
        "label.pending_transactions": "Transaksi tertunda",
        "label.files": "Berkas",
        "label.books": "Kitab",
        "label.verse_units": "Unit ayat",
        "label.sections": "Bagian",
        "label.paragraphs": "Paragraf",
        "label.setting": "Pengaturan",
        "label.resolved": "Diselesaikan",
        "label.confidence": "Keyakinan",
        "label.original": "Asli",
        "label.effective_value": "Nilai efektif",
        "label.method": "Metode",
        "label.source_settings_sha256": "SHA-256 pengaturan sumber",
        "label.confirmed_resolutions": "Penyelesaian yang dikonfirmasi",
        "report.init_preserves_source": "INIT mempertahankan berkas pengaturan sumber. Koreksi yang dikonfirmasi ditulis ke sidecar konfigurasi efektif yang dikelola dan divalidasi ulang sebelum digunakan.",
        "report.confirm_project_fields": "Konfirmasikan status aktif, perutean bahasa/profil, status isi, cakupan, peran, dan otoritas VRS. Tidak ada koreksi yang diterapkan secara diam-diam.",
        "report.guided_init_next": "Gunakan INIT terpandu untuk mengoreksi pengaturan yang dapat dipulihkan pada sidecar yang dikelola, atau edit YAML sumber secara sengaja lalu jalankan ulang INIT. Edit sumber membuat sidecar lama tidak berlaku.",
        "label.version": "Versi",
        "label.projects_root": "Akar proyek",
        "label.effective_overrides": "Penimpaan efektif",
        "label.workflows": "Alur kerja",
        "label.projects": "Proyek",
        "label.auto_resolved_settings": "Pengaturan yang diselesaikan otomatis",
        "label.operator_resolution_history": "Riwayat penyelesaian Operator",
        "label.restrictions_errors": "Pembatasan dan kesalahan",
        "label.next_action": "Tindakan berikutnya",
        "label.settings": "Pengaturan",
        "label.interactive_review": "Peninjauan interaktif",
        "label.effective_configuration": "Konfigurasi efektif",
        "label.unregistered_project_folders": "Folder proyek yang belum ditambahkan ke SAGE",
        "label.auto_resolution_review": "Peninjauan penyelesaian otomatis",
        "label.operator_confirmed_fields": "Bidang yang dikonfirmasi Operator",
        "label.yes": "YA",
        "label.no": "TIDAK",
        "label.none": "Tidak ada",
        "label.no_auto_settings": "Tidak ada pengaturan otomatis",
        "label.no_operator_corrections": "Tidak ada koreksi Operator",
        "label.no_unregistered_projects": "Tidak ada folder proyek yang tersisa di luar SAGE",
        "label.canonical_fallback": "Pesan sumber yang belum dilokalkan ditampilkan dalam bentuk kanonis.",
        "report.auto_resolution": "Laporan penyelesaian otomatis SAGE",
        "report.auto_resolution_intro": "Setiap pengaturan yang dinyatakan sebagai `auto` tercantum di sini. SAGE tidak menulis ulang YAML sumber.",
        "report.auto_resolution_edit": "Operator dapat mengganti nilai `auto` dengan nilai eksplisit lalu menjalankan ulang inisialisasi.",
        "label.resolved_value": "Nilai terselesaikan",
        "label.source": "Sumber",
        "label.override": "Penimpaan",
        "label.impact_notes": "Catatan dampak",
        "report.act_submission": "Pengiriman ACT SAGE",
        "label.challenge_report": "Laporan tantangan",
        "prompt.value_not_recognised": "{label} {received} tidak dikenali.",
        "prompt.value_required": "{label} wajib diisi.",
        "prompt.possible_corrections": "Kemungkinan koreksi:",
        "prompt.confidence": "keyakinan",
        "prompt.enter_another_value": "Masukkan nilai lain",
        "prompt.cancel": "Batal",
        "prompt.selection": "Pilihan: ",
        "prompt.enter_listed_number": "Masukkan salah satu nomor yang tercantum.",
        "prompt.enter_value": "Masukkan {label}: ",
        "prompt.resolved_value": "{label} diselesaikan: {original} -> {corrected}",
        "prompt.use_correction": "Gunakan koreksi ini? [Y/n/edit] ",
        "prompt.configured_false": "Ekosistem dinyatakan configured: false.",
        "prompt.configured_override": "INIT dapat menandai konfigurasi efektif sebagai terkonfigurasi tanpa menulis ulang ecosystem.yml.",
        "prompt.auto_setting": "Pengaturan otomatis",
        "prompt.proposed_value": "Nilai yang diusulkan",
        "prompt.basis": "Dasar",
        "prompt.no_change": "Tidak ada perubahan yang dicatat.",
        "prompt.project_disabled": "Proyek {project_id} terdaftar tetapi dinonaktifkan dalam konfigurasi efektif.",
        "fallback.unavailable": "Teks bahasa kedua tidak tersedia; teks kanonis ditampilkan.",
    },
}


def _language_token(value: Any, label: str) -> str:
    """Validate an explicit language tag or one governed dynamic language alias."""
    token = require_string(value, label)
    upper = token.upper()
    if upper in _LANGUAGE_ALIASES:
        return upper
    return canonical_language_tag(token, label)


def _optional_language_token(value: Any, label: str) -> str | None:
    """Validate one optional language token."""
    if value in (None, ""):
        return None
    return _language_token(value, label)


def parse_human_output(raw: Any) -> HumanOutputSpec:
    """Parse independent log/report and translation-challenge language settings."""
    root = require_mapping(raw or {}, "human_output")
    operator_language = canonical_language_tag(
        require_string(root.get("operator_language", "en"), "human_output.operator_language"),
        "human_output.operator_language",
    )
    logs = require_mapping(root.get("logs_and_reports", {}), "human_output.logs_and_reports")
    challenges = require_mapping(
        root.get("translation_challenges", {}),
        "human_output.translation_challenges",
    )
    machine = require_mapping(root.get("machine_records", {}), "human_output.machine_records")
    verbosity = str(logs.get("verbosity", "normal")).strip().lower()
    if verbosity not in _VERBOSITY:
        raise ConfigurationError(
            "human_output.logs_and_reports.verbosity must be quiet, normal, verbose, or debug"
        )
    minimum = challenges.get("minimum_individual_urgency", 2)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0 or minimum > 4:
        raise ConfigurationError(
            "human_output.translation_challenges.minimum_individual_urgency must be 0-4"
        )
    machine_language = require_string(
        machine.get("language", "canonical"),
        "human_output.machine_records.language",
    ).lower()
    if machine_language != "canonical":
        raise ConfigurationError("human_output.machine_records.language must be canonical")
    return HumanOutputSpec(
        operator_language=operator_language,
        logs_and_reports=OutputLanguageChannel(
            primary_language=_language_token(
                logs.get("primary_language", "OPERATOR_LANGUAGE"),
                "human_output.logs_and_reports.primary_language",
            ),
            secondary_language=_optional_language_token(
                logs.get("secondary_language", "en"),
                "human_output.logs_and_reports.secondary_language",
            ),
            bilingual=bool(logs.get("bilingual", True)),
        ),
        translation_challenges=TranslationChallengeChannel(
            primary_language=_language_token(
                challenges.get("primary_language", "SOURCE_LANGUAGE"),
                "human_output.translation_challenges.primary_language",
            ),
            secondary_language=_optional_language_token(
                challenges.get("secondary_language", "en"),
                "human_output.translation_challenges.secondary_language",
            ),
            bilingual=bool(challenges.get("bilingual", True)),
            minimum_individual_urgency=minimum,
            aggregate_lower_levels=bool(challenges.get("aggregate_lower_levels", True)),
            consolidate_repeated_cause=bool(challenges.get("consolidate_repeated_cause", True)),
            render_only_material_fields=bool(challenges.get("render_only_material_fields", True)),
        ),
        machine_language=machine_language,
        localise_codes=bool(machine.get("localise_codes", False)),
        verbosity=verbosity,
    )


def resolve_language_token(
    token: str,
    *,
    operator_language: str,
    source_language: str | None = None,
    target_language: str | None = None,
    reference_language: str | None = None,
) -> str:
    """Resolve one dynamic language alias without changing canonical machine values."""
    mapping = {
        "OPERATOR_LANGUAGE": operator_language,
        "SOURCE_LANGUAGE": source_language,
        "TARGET_LANGUAGE": target_language,
        "REFERENCE_LANGUAGE": reference_language,
    }
    if token in mapping:
        value = mapping[token]
        if value:
            return value
        return operator_language
    return token


def resolved_languages(
    channel: OutputLanguageChannel,
    *,
    operator_language: str,
    source_language: str | None = None,
    target_language: str | None = None,
    reference_language: str | None = None,
) -> tuple[str, ...]:
    """Resolve configured language tokens and remove repeated effective languages."""
    result: list[str] = []
    for token in channel.tokens():
        value = resolve_language_token(
            token,
            operator_language=operator_language,
            source_language=source_language,
            target_language=target_language,
            reference_language=reference_language,
        )
        if value not in result:
            result.append(value)
    return tuple(result)


def catalogue_text(language: str, key: str) -> str:
    """Return an approved catalogue string, falling back to canonical English."""
    language_catalogue = _CATALOGUE.get(language, {})
    return language_catalogue.get(key) or _CATALOGUE["en"].get(key) or key


def paired_catalogue_text(
    channel: OutputLanguageChannel,
    key: str,
    *,
    operator_language: str,
    source_language: str | None = None,
    target_language: str | None = None,
    reference_language: str | None = None,
    separator: str = " / ",
) -> str:
    """Render one approved label in the configured channel language order."""
    languages = resolved_languages(
        channel,
        operator_language=operator_language,
        source_language=source_language,
        target_language=target_language,
        reference_language=reference_language,
    )
    values = [catalogue_text(language, key) for language in languages]
    return separator.join(values)


def message_for_languages(
    messages: Mapping[str, Any],
    field: str,
    languages: tuple[str, ...],
    *,
    fallback: str,
) -> str:
    """Render model-supplied localised challenge text without inventing missing wording."""
    values: list[str] = []
    for language in languages:
        row = messages.get(language)
        value = row.get(field) if isinstance(row, Mapping) else None
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif fallback and fallback not in values:
            values.append(fallback)
    return " / ".join(values) if values else fallback


_CONSOLE_EXACT_KEYS = {
    "SAGE INPUT REMEDIATION": "report.input_remediation",
    "SAGE PROJECT INIT": "report.project_init",
    "SAGE ACT WORK-UNIT PLAN": "report.act_work_unit_plan",
    "SAGE ACT TASK": "report.act_task",
    "SAGE ACT AGGREGATE": "report.act_aggregate",
    "SAGE BIC MEMORY REVIEW PROVENANCE": "report.bic_memory_review_provenance",
    "SAGE PROJECT STATE RESET": "report.project_state_reset",
    "SAGE EVALUATION QUEUE": "report.evaluation_queue",
    "SAGE INITIALISATION RESULT": "report.initialisation_result",
    "SAGE VALIDATION RESULT": "report.validation_result",
    "SAGE STATUS": "report.status_summary",
    "SAGE PROJECTS": "report.project_registry",
    "SAGE WORK-UNIT PLAN": "report.work_unit_plan",
    "SAGE TRANSACTION RECOVERY": "report.transaction_recovery",
    "SAGE TARGET GENERATION PUBLICATION": "report.generation_publication",
    "SAGE TARGET GENERATION VERIFICATION": "report.generation_verification",
    "SAGE DOCTOR": "report.doctor",
    "SAGE REQUEST INTERPRETATION": "report.request_interpretation",
    "RELATED SUPPORTED OPERATIONS": "report.related_operations",
    "RELATED REGISTERED COMMANDS": "report.related_commands",
    "SAGE COMMAND EXPLANATION": "report.command_explanation",
    "SAGE ERROR": "report.error",
    "Projects and configuration were preserved.": "message.projects_preserved",
    "All normal SAGE parsing, INIT, scope, grammar, review, transaction, and write controls still apply.": "message.controls_still_apply",
    "No command is safe to recommend for execution.": "message.no_safe_command",
    "Advisory-only mode selected. No project command was executed.": "message.advisory_only",
}

_CONSOLE_PREFIX_KEYS = {
    "Status": "label.status",
    "State": "label.state",
    "Capability": "label.capability",
    "Effective configured": "label.effective_configured",
    "Version": "label.version",
    "Plan": "label.plan",
    "Workflow": "label.workflow",
    "Operation": "label.operation",
    "Requested scope": "label.requested_scope",
    "Scope": "label.scope",
    "Work units": "label.work_units",
    "Plan file": "label.plan_file",
    "Task": "label.task",
    "Output project": "label.output_project",
    "Contemporary source": "label.contemporary_source",
    "Focus": "label.focus",
    "ACT prompt": "label.act_prompt",
    "Decision": "label.decision",
    "Review ID": "label.review_id",
    "Removed entries": "label.removed_entries",
    "Set": "label.set",
    "Mode": "label.mode",
    "Queue": "label.queue",
    "Projects": "label.projects",
    "Errors": "label.errors",
    "Restrictions": "label.restrictions",
    "Auto settings": "label.auto_settings",
    "Report": "label.report",
    "Auto report": "label.auto_report",
    "Next": "label.next",
    "Qualification": "label.qualification",
    "Runtime": "label.runtime",
    "Resources": "label.resources",
    "Pending transactions": "label.pending_transactions",
    "Execution available": "label.execution_available",
    "Project": "label.project",
    "Primary coordinates": "label.primary_coordinates",
    "Reviewed coordinates": "label.reviewed_coordinates",
    "Findings": "label.findings",
    "Aggregate": "label.aggregate",
    "Target generation basis": "label.target_generation_basis",
    "Largest estimated packet tokens": "label.largest_estimated_tokens",
    "Largest serialized packet bytes": "label.largest_serialized_bytes",
    "Manifest": "label.manifest",
    "Transaction": "label.transaction",
    "Pending": "label.pending",
    "Generation": "label.generation",
    "Publication basis": "label.publication_basis",
    "Reused": "label.reused",
    "Path": "label.path",
    "Consumer": "label.consumer",
    "State file": "label.state_file",
    "Verification": "label.verification",
    "Project snapshot": "label.project_snapshot",
    "Integrity status": "label.integrity_status",
    "Python": "label.python",
    "PyYAML": "label.pyyaml",
    "Settings": "label.settings_path",
    "Projects root": "label.projects_root",
    "Request": "label.request",
    "Result": "label.result",
    "Read-only command": "label.read_only_command",
    "Changes SAGE runtime state": "label.changes_runtime_state",
    "Details": "label.details",
    "Reason code": "label.reason_code",
    "Message": "label.message",
    "Affected scope": "label.affected_scope",
    "Suggested alternative": "label.suggested_alternative",
    "ERROR": "label.errors",
    "WARNING": "label.restrictions",
}


def paired_label_value_text(
    channel: OutputLanguageChannel,
    key: str,
    value: str,
    *,
    operator_language: str,
    source_language: str | None = None,
    target_language: str | None = None,
    reference_language: str | None = None,
) -> str:
    """Render one labelled value in every configured language without altering the value."""
    languages = resolved_languages(
        channel,
        operator_language=operator_language,
        source_language=source_language,
        target_language=target_language,
        reference_language=reference_language,
    )
    return " / ".join(f"{catalogue_text(language, key)}: {value}" for language in languages)


class LocalizedConsoleStream:
    """Localise recognised report headings and labels while preserving canonical values."""

    def __init__(
        self,
        stream: TextIO,
        *,
        spec: HumanOutputSpec,
        source_language: str | None = None,
        target_language: str | None = None,
        reference_language: str | None = None,
    ) -> None:
        """Wrap one text stream and retain partial writes until a complete line is available."""
        self.stream = stream
        self.spec = spec
        self.source_language = source_language
        self.target_language = target_language
        self.reference_language = reference_language
        self._buffer = ""

    @property
    def encoding(self) -> str | None:
        """Expose the wrapped stream encoding for standard-library compatibility."""
        return getattr(self.stream, "encoding", None)

    def isatty(self) -> bool:
        """Return the wrapped stream terminal status."""
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def fileno(self) -> int:
        """Return the wrapped stream file descriptor."""
        return self.stream.fileno()

    def flush(self) -> None:
        """Flush a pending partial line and then the wrapped stream."""
        if self._buffer:
            self.stream.write(self._render_line(self._buffer))
            self._buffer = ""
        self.stream.flush()

    def write(self, text: str) -> int:
        """Write text after localising complete human-facing report lines."""
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.stream.write(self._render_line(line) + "\n")
        return len(text)

    def _render_line(self, line: str) -> str:
        """Localise one recognised line and leave commands, JSON, IDs, and diagnostics intact."""
        if not line.strip() or line.lstrip().startswith(("{", "[")):
            return line
        stripped = line.strip()
        if len(stripped) >= 9 and stripped[2:3] == ":" and stripped[5:6] == ":":
            return line
        indent = line[: len(line) - len(line.lstrip())]
        exact_key = _CONSOLE_EXACT_KEYS.get(stripped)
        if exact_key:
            return indent + paired_catalogue_text(
                self.spec.logs_and_reports,
                exact_key,
                operator_language=self.spec.operator_language,
                source_language=self.source_language,
                target_language=self.target_language,
                reference_language=self.reference_language,
            )
        if stripped.endswith(" WORKFLOW STATUS"):
            workflow = stripped[: -len(" WORKFLOW STATUS")]
            heading = paired_catalogue_text(
                self.spec.logs_and_reports,
                "report.workflow_status",
                operator_language=self.spec.operator_language,
            )
            return f"{indent}{workflow} — {heading}"
        if stripped.startswith("SAGE TARGET GENERATIONS — "):
            project = stripped.split("—", 1)[1].strip()
            heading = paired_catalogue_text(
                self.spec.logs_and_reports,
                "report.target_generations",
                operator_language=self.spec.operator_language,
            )
            return f"{indent}{heading} — {project}"
        if stripped.endswith(" TRANSACTIONS") and stripped != "TRANSACTIONS":
            workflow = stripped[: -len(" TRANSACTIONS")]
            heading = paired_catalogue_text(
                self.spec.logs_and_reports,
                "report.transactions",
                operator_language=self.spec.operator_language,
            )
            return f"{indent}{workflow} — {heading}"
        for prefix, key in _CONSOLE_PREFIX_KEYS.items():
            marker = prefix + ":"
            if stripped.startswith(marker):
                value = stripped[len(marker) :].strip()
                rendered = paired_label_value_text(
                    self.spec.logs_and_reports,
                    key,
                    value,
                    operator_language=self.spec.operator_language,
                    source_language=self.source_language,
                    target_language=self.target_language,
                    reference_language=self.reference_language,
                )
                return indent + rendered
        return line


class OperationalLogger:
    """Append canonical JSONL events and render concise localised console lines."""

    def __init__(
        self,
        *,
        root: Path,
        spec: HumanOutputSpec,
        mode: str | None = None,
        stream: TextIO | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        reference_language: str | None = None,
    ) -> None:
        """Prepare one logger without creating its runtime directory until first use."""
        self.root = root
        self.spec = spec
        self.mode = mode or spec.verbosity
        if self.mode not in _VERBOSITY:
            raise ConfigurationError(f"Unsupported operational-log mode: {self.mode}")
        self.stream = stream or sys.stdout
        self.source_language = source_language
        self.target_language = target_language
        self.reference_language = reference_language
        self.path = root / "workspace-data" / "sage" / "logs" / "operational.jsonl"
        self.human_path = root / "workspace-data" / "sage" / "logs" / "operational.log"

    def emit(
        self,
        event_code: str,
        *,
        severity: str = "INFO",
        context: Mapping[str, Any] | None = None,
        console: bool = True,
    ) -> dict[str, Any]:
        """Write one canonical event and optionally print one readable localised line."""
        severity = severity.upper()
        if severity not in _SEVERITY_ORDER:
            raise ConfigurationError(f"Unsupported operational-log severity: {severity}")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record = {
            "timestamp_utc": timestamp,
            "severity": severity,
            "event_code": event_code,
            "context": dict(context or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        message = paired_catalogue_text(
            self.spec.logs_and_reports,
            f"event.{event_code}",
            operator_language=self.spec.operator_language,
            source_language=self.source_language,
            target_language=self.target_language,
            reference_language=self.reference_language,
        )
        context_text = " ".join(
            f"{key}={value}" for key, value in sorted(record["context"].items()) if value not in (None, "")
        )
        clock = timestamp[11:19]
        suffix = f"  {context_text}" if context_text else ""
        human_line = f"{clock} {severity:<8} {message}{suffix}"
        with self.human_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(human_line + "\n")
        if console and _SEVERITY_ORDER[severity] >= _MODE_THRESHOLD[self.mode]:
            print(human_line, file=self.stream)
        return record
