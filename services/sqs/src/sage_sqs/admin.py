"""SSH-only SQS ADMIN console.

All mutations operate directly on the local repository. The console never
exposes a method for manually entering measured qualification results.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

import yaml

from .db import Database
from .domain import Qualification
from .publisher import Publisher
from .providers.openai_provider import load_openai_catalog, sync_provider_catalog
from .repository import Repository

_MENU = """1. Review attention items
2. Language profiles
3. OpenAI models
4. Qualifications
5. Run / review evaluations
6. Host discoveries
7. Publish bundle
8. Logs / audit
9. Service status
0. Exit"""


class AdminApp:
    def __init__(self, repo: Repository, *, publisher: Publisher):
        self.repo = repo
        self.publisher = publisher

    def menu_text(self) -> str:
        return _MENU

    def status_snapshot(self) -> dict[str, int | str]:
        conn = self.repo.db.connection
        count = lambda sql, params=(): int(conn.execute(sql, params).fetchone()[0])
        bundle = self.repo.current_published_bundle()
        return {
            "bundle_revision": int(bundle["bundle_revision"]) if bundle else 0,
            "profiles_active": count("SELECT COUNT(*) FROM profiles WHERE status='ACTIVE'"),
            "profiles_review": count("SELECT COUNT(*) FROM profiles WHERE status='REVIEW_REQUIRED'"),
            "models_approved": count("SELECT COUNT(*) FROM models WHERE status='APPROVED'"),
            "models_disabled": count("SELECT COUNT(*) FROM models WHERE status='DISABLED'"),
            "qualified": count("SELECT COUNT(*) FROM qualifications WHERE json_extract(payload_json,'$.status')='QUALIFIED'"),
            "not_qualified": count("SELECT COUNT(*) FROM qualifications WHERE json_extract(payload_json,'$.status')='NOT_QUALIFIED'"),
            "medium_confidence": count("SELECT COUNT(*) FROM qualifications WHERE json_extract(payload_json,'$.confidence')='MEDIUM'"),
            "low_confidence": count("SELECT COUNT(*) FROM qualifications WHERE json_extract(payload_json,'$.confidence')='LOW'"),
            "tests_pruned": count("SELECT COUNT(*) FROM planner_events WHERE disposition='PRUNE'"),
            "tests_deferred": count("SELECT COUNT(*) FROM planner_events WHERE disposition='DEFER'"),
            "attention": len(self.repo.list_attention()),
            "pending_evaluations": count("SELECT COUNT(*) FROM evaluation_runs WHERE status='PENDING'"),
            "running_evaluations": count("SELECT COUNT(*) FROM evaluation_runs WHERE status='RUNNING'"),
        }

    def render_home(self) -> None:
        s = self.status_snapshot()
        print("SAGE Qualification Service (SQS) 0.02a1")
        print("=======================================")
        print()
        print("Service")
        print("-------")
        print("Database                OK")
        print(f"Evaluation worker       {'BUSY' if s['running_evaluations'] else 'IDLE'}")
        print(f"Published bundle        rev {s['bundle_revision']}")
        print()
        print("Profiles")
        print("--------")
        print(f"Active                  {s['profiles_active']}")
        print(f"Review required         {s['profiles_review']}")
        print()
        print("OpenAI models")
        print("-------------")
        print(f"Approved                {s['models_approved']}")
        print(f"Disabled                {s['models_disabled']}")
        print()
        print("Qualifications")
        print("--------------")
        print(f"Qualified               {s['qualified']}")
        print(f"Not qualified           {s['not_qualified']}")
        print(f"Medium confidence       {s['medium_confidence']}")
        print(f"Low confidence          {s['low_confidence']}")
        print()
        print("Efficiency")
        print("----------")
        print(f"Tests pruned            {s['tests_pruned']}")
        print(f"Tests deferred          {s['tests_deferred']}")
        print()
        print(f"Attention required      {s['attention']}")

    def approve_profile(self, profile_id: str) -> None:
        profile = self.repo.latest_profile(profile_id)
        if profile is None:
            raise ValueError("UNKNOWN_PROFILE")
        if profile.status == "RETIRED":
            raise ValueError("RETIRED_PROFILE")
        self.repo.save_profile(replace(profile, status="ACTIVE"))
        self.repo.audit("ADMIN", "APPROVE_PROFILE", {"profile_id": profile_id, "revision": profile.revision})

    def retire_profile(self, profile_id: str) -> None:
        profile = self.repo.latest_profile(profile_id)
        if profile is None:
            raise ValueError("UNKNOWN_PROFILE")
        self.repo.save_profile(replace(profile, status="RETIRED"))
        self.repo.audit("ADMIN", "RETIRE_PROFILE", {"profile_id": profile_id, "revision": profile.revision})

    def approve_model(self, model_id: str, *, provider_family: str = "openai") -> None:
        model = self.repo.latest_model(provider_family, model_id)
        if model is None:
            raise ValueError("UNKNOWN_MODEL")
        if not model.tier_mapping_approved:
            raise ValueError("TIER_MAPPING_NOT_APPROVED")
        self.repo.save_model(replace(model, status="APPROVED"))
        self.repo.audit("ADMIN", "APPROVE_MODEL", {"provider_family": provider_family, "model_id": model_id, "revision": model.revision})

    def approve_tier_mapping(self, model_id: str, *, provider_family: str = "openai", reasoning_tiers=None) -> None:
        model = self.repo.latest_model(provider_family, model_id)
        if model is None:
            raise ValueError("UNKNOWN_MODEL")
        tiers = tuple(reasoning_tiers) if reasoning_tiers is not None else model.reasoning_tiers
        if not tiers:
            raise ValueError("TIER_MAPPING_EMPTY")
        approved = replace(
            model, reasoning_tiers=tiers,
            tier_mapping_revision=max(1, model.tier_mapping_revision + (1 if reasoning_tiers is not None else 0)),
            tier_mapping_fingerprint="", tier_mapping_approved=True,
        )
        self.repo.save_model(approved)
        self.repo.resolve_attention(f"TIER_MAPPING_REVIEW:{provider_family}:{model_id}:{model.revision}")
        self.repo.audit("ADMIN", "APPROVE_TIER_MAPPING", {
            "provider_family": provider_family, "model_id": model_id, "revision": model.revision,
            "tier_mapping_revision": approved.tier_mapping_revision,
            "tier_mapping_fingerprint": approved.tier_mapping_fingerprint,
            "reasoning_tiers": [tier.public_dict() for tier in approved.reasoning_tiers],
        })

    def disable_model(self, model_id: str, *, provider_family: str = "openai") -> None:
        model = self.repo.latest_model(provider_family, model_id)
        if model is None:
            raise ValueError("UNKNOWN_MODEL")
        self.repo.save_model(replace(model, status="DISABLED"))
        self.repo.audit("ADMIN", "DISABLE_MODEL", {"provider_family": provider_family, "model_id": model_id, "revision": model.revision})

    def refresh_provider_metadata(self, path: Path):
        rows = sync_provider_catalog(self.repo, load_openai_catalog(path))
        self.repo.audit("ADMIN", "REFRESH_PROVIDER_METADATA", {
            "path": str(path),
            "models_seen": len(rows),
            "models_changed": sum(1 for row in rows if row.changed),
        })
        return rows

    def draft_language_profile_seed(self, *, profile_id: str, language_code: str, script: str,
                                    region: str, requested_capability: str, seed_dir: Path) -> Path:
        """Write a seed/languages/<profile_id>.yml identity stub from a validation request.

        Only the identity fields observable from the request are filled in.
        tier, cluster, iso_639_3, and display_name are left as explicit
        placeholders that fail validate_profile() until ADMIN sets them --
        those are business/linguistic judgment calls, not something this
        console fabricates. Never overwrites an existing seed file.
        """
        seed_dir = Path(seed_dir)
        path = seed_dir / f"{profile_id}.yml"
        if path.exists():
            raise ValueError("SEED_FILE_ALREADY_EXISTS")
        seed_dir.mkdir(parents=True, exist_ok=True)
        stub = {
            "schema_version": "1.0",
            "profile_id": profile_id,
            "display_name": profile_id,
            "status": "DRAFT",
            "revision": 1,
            "tier": 0,
            "cluster": "",
            "identity": {
                "iso_639_1": language_code,
                "iso_639_3": "",
                "script": script,
                "region": region,
            },
            "capabilities": ["GRAMMAR_ANALYSIS", "SEMANTIC_REWRITE"],
            "profile_build": {
                "source": "LANGUAGE_VALIDATION_REQUEST",
                "sage_profile_available_in_reference_snapshot": True,
                "exact_profile_confirmation_required": True,
                "evaluation_pack_state": "BUILD_REQUIRED",
            },
            "admin_review": {"required": True, "issues": []},
        }
        path.write_text(yaml.safe_dump(stub, sort_keys=False), encoding="utf-8")
        self.repo.audit("ADMIN", "DRAFT_LANGUAGE_PROFILE_SEED", {
            "profile_id": profile_id, "requested_capability": requested_capability, "path": str(path),
        })
        return path

    def queue_evaluation(self, *, model_id: str, profile_id: str, capability: str,
                         reasoning: str = "medium", scope: str = "FULL", force: bool = False) -> dict:
        profile = self.repo.latest_profile(profile_id)
        model = self.repo.latest_model("openai", model_id)
        if profile is None or profile.status != "ACTIVE":
            raise ValueError("PROFILE_NOT_ACTIVE")
        if model is None or model.status != "APPROVED":
            raise ValueError("MODEL_NOT_APPROVED")
        item = self.repo.queue_test({
            "provider_family": "openai",
            "profile_id": profile_id,
            "model_id": model_id,
            "capability": capability,
            "reasoning": reasoning,
            "scope": scope,
        }, force=force)
        self.repo.audit("ADMIN", "QUEUE_EVALUATION", {"run_id": item["id"], "profile_id": profile_id, "model_id": model_id, "capability": capability})
        return item

    def revoke_qualification(self, *, model_id: str, profile_id: str, capability: str,
                             provider_family: str = "openai") -> None:
        self.repo.db.connection.execute(
            "DELETE FROM qualifications WHERE provider_family=? AND model_id=? AND profile_id=? AND capability=?",
            (provider_family, model_id, profile_id, capability),
        )
        self.repo.db.connection.commit()
        self.repo.audit("ADMIN", "REVOKE_QUALIFICATION", {
            "provider_family": provider_family, "model_id": model_id, "profile_id": profile_id, "capability": capability,
        })

    def review_qualification_submission(self, attention_key: str, *, decision: str) -> None:
        if decision not in ("APPROVE", "REJECT"):
            raise ValueError("INVALID_DECISION")
        row = next((item for item in self.repo.list_attention() if item["attention_key"] == attention_key), None)
        if row is None or row["category"] != "QUALIFICATION_SUBMISSION":
            raise ValueError("UNKNOWN_SUBMISSION")
        payload = row["payload"]
        run_id = str(payload["run_id"])
        if decision == "REJECT":
            self.repo.fail_evaluation(run_id, "SUBMISSION_REJECTED")
            self.repo.resolve_attention(attention_key)
            self.repo.audit("ADMIN", "REJECT_QUALIFICATION_SUBMISSION", {"run_id": run_id, "attention_key": attention_key})
            return
        qualification = Qualification(**payload["qualification"])
        # publishable_qualifications() silently drops any row whose identity
        # fingerprints don't match the CURRENT profile/model records -- if
        # either was revised between when this submission was prepared and
        # now, approving it here would look successful but the result would
        # never actually publish, with no signal to ADMIN. Re-check the same
        # identity the publish-time filter checks, and fail closed instead.
        profile = self.repo.latest_profile(qualification.profile_id)
        if profile is None or profile.evaluation_identity_sha256 != qualification.profile_identity_sha256:
            raise ValueError("SUBMISSION_PROFILE_IDENTITY_STALE")
        model = self.repo.latest_model(qualification.provider_family, qualification.model_id)
        if model is None or model.capability_fingerprint != qualification.model_capability_fingerprint:
            raise ValueError("SUBMISSION_MODEL_FINGERPRINT_STALE")
        self.repo.save_qualification(qualification)
        self.repo.save_evaluation_attempt(run_id, payload["attempt"])
        self.repo.complete_evaluation(run_id)
        self.repo.resolve_attention(attention_key)
        self.repo.audit("ADMIN", "APPROVE_QUALIFICATION_SUBMISSION", {"run_id": run_id, "attention_key": attention_key})

    def publish_bundle(self) -> dict:
        return self.publisher.publish(actor="ADMIN")

    def render_attention(self) -> None:
        rows = self.repo.list_attention()
        if not rows:
            print("No open attention items.")
            return
        for row in rows:
            print(f"{row['attention_key']} [{row['severity']}] x{row['observation_count']} - {row['summary']}")

    def render_audit(self, *, limit: int = 50) -> None:
        rows = self.repo.db.connection.execute(
            "SELECT created_utc,actor,action,payload_json FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        for row in rows:
            print(f"{row['created_utc']} {row['actor']} {row['action']} {row['payload_json']}")

    def run(self, input_fn: Callable[[str], str] = input) -> int:
        while True:
            self.render_home()
            print()
            print(self.menu_text())
            choice = input_fn("SQS ADMIN> ").strip()
            if choice == "0":
                return 0
            if choice == "1":
                self.render_attention()
            elif choice == "7":
                bundle = self.publish_bundle()
                print(f"Published bundle rev {bundle['bundle_revision']}")
            elif choice == "8":
                self.render_audit()
            elif choice == "9":
                self.render_home()
            else:
                # Entity mutation workflows are intentionally exposed as explicit
                # methods; scripted SSH administration can call them through the
                # same domain layer without a web ADMIN surface.
                print("Use the explicit ADMIN operation for this entity workflow.")


def _publisher_from_env(repo: Repository) -> Publisher:
    output = Path(os.environ.get("SQS_BUNDLE_PATH", "/var/lib/sage-sqs/public/bundle.json"))
    return Publisher(
        repo,
        authority_id=os.environ.get("SQS_AUTHORITY_ID", "biblica-sqs-production"),
        publication_epoch=int(os.environ.get("SQS_PUBLICATION_EPOCH", "1")),
        output_paths=(output,),
    )


def main() -> int:
    repo = Repository(Database.open(Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))))
    return AdminApp(repo, publisher=_publisher_from_env(repo)).run()
