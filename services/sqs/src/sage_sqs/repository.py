"""SQS repository with explicit publication storage."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .db import Database
from .domain import LanguageProfile, ModelRecord, Qualification, ReasoningTier


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def save_profile(self, profile: LanguageProfile) -> None:
        self.db.connection.execute(
            "INSERT OR REPLACE INTO profiles(profile_id,revision,status,payload_json) VALUES(?,?,?,?)",
            (profile.profile_id, profile.revision, profile.status, _json(asdict(profile))),
        )
        self.db.connection.commit()

    def save_model(self, model: ModelRecord) -> None:
        payload = asdict(model)
        payload["reasoning_levels"] = list(model.reasoning_levels)
        payload["reasoning_tiers"] = [tier.public_dict() for tier in model.reasoning_tiers]
        self.db.connection.execute(
            "INSERT OR REPLACE INTO models(provider_family,model_id,revision,status,payload_json) VALUES(?,?,?,?,?)",
            (model.provider_family, model.model_id, model.revision, model.status, _json(payload)),
        )
        self.db.connection.commit()

    def save_qualification(self, qualification: Qualification) -> None:
        self.db.connection.execute(
            "DELETE FROM qualifications WHERE provider_family=? AND model_id=? AND profile_id=? AND capability=?",
            (qualification.provider_family, qualification.model_id, qualification.profile_id, qualification.capability),
        )
        self.db.connection.execute(
            "INSERT INTO qualifications(provider_family,model_id,profile_id,capability,payload_json) VALUES(?,?,?,?,?)",
            (
                qualification.provider_family,
                qualification.model_id,
                qualification.profile_id,
                qualification.capability,
                _json(asdict(qualification)),
            ),
        )
        self.db.connection.commit()

    def active_profiles(self) -> list[LanguageProfile]:
        rows = self.db.connection.execute(
            "SELECT p.payload_json FROM profiles p JOIN (SELECT profile_id, MAX(revision) revision FROM profiles GROUP BY profile_id) x ON p.profile_id=x.profile_id AND p.revision=x.revision WHERE p.status='ACTIVE' ORDER BY p.profile_id"
        ).fetchall()
        return [LanguageProfile(**json.loads(row[0])) for row in rows]

    def approved_models(self) -> list[ModelRecord]:
        rows = self.db.connection.execute(
            "SELECT m.payload_json FROM models m JOIN (SELECT provider_family, model_id, MAX(revision) revision FROM models GROUP BY provider_family,model_id) x ON m.provider_family=x.provider_family AND m.model_id=x.model_id AND m.revision=x.revision WHERE m.status='APPROVED' ORDER BY m.provider_family,m.model_id"
        ).fetchall()
        result = []
        for row in rows:
            value = json.loads(row[0])
            value["reasoning_levels"] = tuple(value["reasoning_levels"])
            value["reasoning_tiers"] = tuple(ReasoningTier(**item) for item in value.get("reasoning_tiers", []))
            result.append(ModelRecord(**value))
        return result

    def publishable_qualifications(self) -> list[Qualification]:
        profiles = {p.profile_id: p for p in self.active_profiles()}
        models = {(m.provider_family, m.model_id): m for m in self.approved_models()}
        rows = self.db.connection.execute("SELECT payload_json FROM qualifications ORDER BY provider_family,model_id,profile_id,capability").fetchall()
        result: list[Qualification] = []
        for row in rows:
            q = Qualification(**json.loads(row[0]))
            profile = profiles.get(q.profile_id)
            model = models.get((q.provider_family, q.model_id))
            if profile is None or model is None:
                continue
            if q.confidence not in {"HIGH", "MEDIUM"} or q.evidence_basis not in {"MEASURED", "CONFIRMED"}:
                continue
            if q.profile_identity_sha256 != profile.evaluation_identity_sha256:
                continue
            if q.model_capability_fingerprint != model.capability_fingerprint:
                continue
            if q.status == "QUALIFIED" and (not q.minimum_native_reasoning or not q.tier_mapping_fingerprint):
                matches = [tier.native_id for tier in model.reasoning_tiers if tier.canonical_band == q.minimum_reasoning and tier.tier_class == "ROUTINE"]
                if len(matches) != 1:
                    continue
                q = replace(q, minimum_native_reasoning=matches[0], tier_mapping_fingerprint=model.tier_mapping_fingerprint)
            result.append(q)
        return result

    def next_bundle_revision(self) -> int:
        row = self.db.connection.execute("SELECT COALESCE(MAX(revision),0)+1 FROM bundles").fetchone()
        return int(row[0])

    def store_bundle(self, bundle: dict[str, Any]) -> None:
        self.db.connection.execute(
            "INSERT INTO bundles(revision,created_utc,sha256,payload_json) VALUES(?,?,?,?)",
            (bundle["bundle_revision"], bundle["generated_at"], bundle["bundle_sha256"], _json(bundle)),
        )
        self.db.connection.commit()

    def current_published_bundle(self) -> dict[str, Any] | None:
        row = self.db.connection.execute("SELECT payload_json FROM bundles ORDER BY revision DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def audit(self, actor: str, action: str, payload: dict[str, Any]) -> None:
        self.db.connection.execute(
            "INSERT INTO audit_events(created_utc,actor,action,payload_json) VALUES(?,?,?,?)",
            (_utc_now(), actor, action, _json(payload)),
        )
        self.db.connection.commit()

    def record_discovery(self, payload: dict[str, Any]) -> str:
        canonical = _json(payload)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        row = self.db.connection.execute("SELECT observation_count FROM discoveries WHERE fingerprint=?", (digest,)).fetchone()
        if row:
            self.db.connection.execute("UPDATE discoveries SET observation_count=observation_count+1 WHERE fingerprint=?", (digest,))
        else:
            self.db.connection.execute("INSERT INTO discoveries(fingerprint,payload_json,observation_count) VALUES(?,?,1)", (digest, canonical))
        self.db.connection.commit()
        return digest

    def upsert_attention(self, *, attention_key: str, category: str, severity: str,
                         summary: str, payload: dict[str, Any]) -> None:
        now = _utc_now()
        row = self.db.connection.execute(
            "SELECT observation_count FROM attention_items WHERE attention_key=?", (attention_key,)
        ).fetchone()
        if row:
            self.db.connection.execute(
                "UPDATE attention_items SET observation_count=observation_count+1,last_seen_utc=?,severity=?,summary=?,payload_json=? WHERE attention_key=?",
                (now, severity, summary, _json(payload), attention_key),
            )
        else:
            self.db.connection.execute(
                "INSERT INTO attention_items(attention_key,category,severity,status,summary,payload_json,observation_count,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,1,?,?)",
                (attention_key, category, severity, "OPEN", summary, _json(payload), now, now),
            )
        self.db.connection.commit()

    def list_attention(self, *, status: str = "OPEN") -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            "SELECT attention_key,category,severity,status,summary,payload_json,observation_count,first_seen_utc,last_seen_utc FROM attention_items WHERE status=? ORDER BY severity DESC, first_seen_utc, attention_key",
            (status,),
        ).fetchall()
        return [
            {
                "attention_key": row["attention_key"],
                "category": row["category"],
                "severity": row["severity"],
                "status": row["status"],
                "summary": row["summary"],
                "payload": json.loads(row["payload_json"]),
                "observation_count": int(row["observation_count"]),
                "first_seen_utc": row["first_seen_utc"],
                "last_seen_utc": row["last_seen_utc"],
            }
            for row in rows
        ]

    def resolve_attention(self, attention_key: str) -> None:
        self.db.connection.execute(
            "UPDATE attention_items SET status='RESOLVED',last_seen_utc=? WHERE attention_key=?",
            (_utc_now(), attention_key),
        )
        self.db.connection.commit()

    def latest_profile(self, profile_id: str) -> LanguageProfile | None:
        row = self.db.connection.execute(
            "SELECT payload_json FROM profiles WHERE profile_id=? ORDER BY revision DESC LIMIT 1", (profile_id,)
        ).fetchone()
        return LanguageProfile(**json.loads(row[0])) if row else None

    def latest_model(self, provider_family: str, model_id: str) -> ModelRecord | None:
        row = self.db.connection.execute(
            "SELECT payload_json FROM models WHERE provider_family=? AND model_id=? ORDER BY revision DESC LIMIT 1",
            (provider_family, model_id),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        payload["reasoning_levels"] = tuple(payload["reasoning_levels"])
        payload["reasoning_tiers"] = tuple(ReasoningTier(**item) for item in payload.get("reasoning_tiers", []))
        return ModelRecord(**payload)

    def queue_test(self, payload: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        canonical = _json(payload)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        run_id = digest if not force else hashlib.sha256(f"{canonical}:{_utc_now()}".encode("utf-8")).hexdigest()
        existing = self.db.connection.execute(
            "SELECT id,status,payload_json FROM evaluation_runs WHERE id=?", (run_id,)
        ).fetchone()
        if existing:
            return {"id": existing["id"], "status": existing["status"], **json.loads(existing["payload_json"])}
        self.db.connection.execute(
            "INSERT INTO evaluation_runs(id,status,payload_json,created_utc) VALUES(?,?,?,?)",
            (run_id, "PENDING", canonical, _utc_now()),
        )
        self.db.connection.commit()
        return {"id": run_id, "status": "PENDING", **payload}

    def list_pending_evaluations(self) -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            "SELECT id,payload_json FROM evaluation_runs WHERE status='PENDING' ORDER BY created_utc,id"
        ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            items.append({
                "id": row["id"],
                "provider_family": payload.get("provider_family", "openai"),
                "profile_id": payload["profile_id"],
                "model_id": payload["model_id"],
                "capability": payload["capability"],
                "reasoning": payload.get("reasoning", "medium"),
                "scope": payload.get("scope", "FULL"),
            })
        return items

    def evaluation_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.connection.execute(
            "SELECT id,status,payload_json FROM evaluation_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"], **json.loads(row["payload_json"])}

    def claim_next_evaluation(self) -> dict[str, Any] | None:
        conn = self.db.connection
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT id,payload_json FROM evaluation_runs WHERE status='PENDING' ORDER BY created_utc,id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            updated = conn.execute(
                "UPDATE evaluation_runs SET status='RUNNING',claimed_utc=? WHERE id=? AND status='PENDING'",
                (_utc_now(), row["id"]),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            return {"id": row["id"], **json.loads(row["payload_json"])}
        except Exception:
            conn.rollback()
            raise

    def save_evaluation_attempt(self, run_id: str, payload: dict[str, Any]) -> None:
        self.db.connection.execute(
            "INSERT INTO evaluation_attempts(run_id,payload_json,created_utc) VALUES(?,?,?)",
            (run_id, _json(payload), _utc_now()),
        )
        self.db.connection.commit()

    def complete_evaluation(self, run_id: str) -> None:
        self.db.connection.execute(
            "UPDATE evaluation_runs SET status='COMPLETED',completed_utc=?,error_text=NULL WHERE id=?",
            (_utc_now(), run_id),
        )
        self.db.connection.commit()

    def fail_evaluation(self, run_id: str, error_text: str) -> None:
        self.db.connection.execute(
            "UPDATE evaluation_runs SET status='FAILED',completed_utc=?,error_text=? WHERE id=?",
            (_utc_now(), error_text, run_id),
        )
        self.db.connection.commit()

    def evaluation_status(self, run_id: str) -> str | None:
        row = self.db.connection.execute("SELECT status FROM evaluation_runs WHERE id=?", (run_id,)).fetchone()
        return str(row[0]) if row else None

    def attempt_count(self, run_id: str) -> int:
        row = self.db.connection.execute("SELECT COUNT(*) FROM evaluation_attempts WHERE run_id=?", (run_id,)).fetchone()
        return int(row[0])

    def record_planner_event(self, *, disposition: str, reason_code: str, payload: dict[str, Any]) -> None:
        self.db.connection.execute(
            "INSERT INTO planner_events(created_utc,disposition,reason_code,payload_json) VALUES(?,?,?,?)",
            (_utc_now(), disposition, reason_code, _json(payload)),
        )
        self.db.connection.commit()

    def link_predecessor(self, model_id: str, predecessor_model_id: str, *, provider_family: str = "openai") -> None:
        self.db.connection.execute(
            "INSERT OR REPLACE INTO model_predecessors(provider_family,model_id,predecessor_model_id) VALUES(?,?,?)",
            (provider_family, model_id, predecessor_model_id),
        )
        self.db.connection.commit()

    def predecessor_model_id(self, model_id: str, *, provider_family: str = "openai") -> str | None:
        row = self.db.connection.execute(
            "SELECT predecessor_model_id FROM model_predecessors WHERE provider_family=? AND model_id=?",
            (provider_family, model_id),
        ).fetchone()
        return str(row[0]) if row else None

    def predecessor_boundary(self, model_id: str, profile_id: str, capability: str,
                             *, provider_family: str = "openai") -> str | None:
        predecessor = self.predecessor_model_id(model_id, provider_family=provider_family)
        if predecessor is None:
            return None
        row = self.db.connection.execute(
            "SELECT payload_json FROM qualifications WHERE provider_family=? AND model_id=? AND profile_id=? AND capability=? ORDER BY id DESC LIMIT 1",
            (provider_family, predecessor, profile_id, capability),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        if payload.get("status") != "QUALIFIED":
            return None
        reasoning = payload.get("minimum_reasoning")
        return reasoning if reasoning in {"low", "medium", "high"} else None

    def pending_evaluation_count(self) -> int:
        row = self.db.connection.execute(
            "SELECT COUNT(*) FROM evaluation_runs WHERE status='PENDING'"
        ).fetchone()
        return int(row[0])

    def all_qualifications(self) -> list[Qualification]:
        rows = self.db.connection.execute(
            "SELECT payload_json FROM qualifications ORDER BY id"
        ).fetchall()
        return [Qualification(**json.loads(row[0])) for row in rows]
