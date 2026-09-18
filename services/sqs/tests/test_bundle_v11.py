from dataclasses import replace
from pathlib import Path

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification, ReasoningTier
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository


def _profile():
    return LanguageProfile('en-US','English','ACTIVE',1,1,'germanic','en','eng','Latn','US')


def test_new_publications_are_1_1_and_include_approved_native_tier_mapping(tmp_path: Path):
    repo = Repository(Database.open(tmp_path/'sqs.db'))
    p = _profile(); repo.save_profile(p)
    tiers = (
        ReasoningTier('off',0,None,'OFF'),
        ReasoningTier('basic',10,'low','ROUTINE'),
        ReasoningTier('standard',20,'medium','ROUTINE'),
        ReasoningTier('deep',30,'high','ROUTINE'),
        ReasoningTier('extreme',40,'high','PREMIUM'),
    )
    m = ModelRecord('other','model-x','APPROVED',1,('basic','standard','deep','extreme'),'abc',1,2, reasoning_tiers=tiers, tier_mapping_revision=1)
    repo.save_model(m)
    q = Qualification('other','model-x',m.capability_fingerprint,p.profile_id,p.evaluation_identity_sha256,'GRAMMAR_ANALYSIS','QUALIFIED','medium',0.9,0.9,'HIGH','HIGH','MEASURED',0.01,'2026-08-31T00:00:00Z','e'*64, minimum_native_reasoning='standard', tier_mapping_fingerprint=m.tier_mapping_fingerprint)
    repo.save_qualification(q)
    bundle = Publisher(repo, authority_id='a', publication_epoch=1, output_paths=[]).publish(actor='ADMIN')
    assert bundle['schema_version'] == '1.1'
    model = bundle['models'][0]
    assert model['reasoning_tiers'][2]['native_id'] == 'standard'
    assert model['reasoning_tiers'][2]['canonical_band'] == 'medium'
    assert model['tier_mapping_revision'] == 1
    qual = bundle['qualifications'][0]
    assert qual['minimum_reasoning'] == 'medium'
    assert qual['minimum_native_reasoning'] == 'standard'
    assert qual['tier_mapping_fingerprint'] == model['tier_mapping_fingerprint']


def test_not_qualified_uses_null_canonical_and_native_reasoning(tmp_path: Path):
    repo = Repository(Database.open(tmp_path/'sqs.db'))
    p = _profile(); repo.save_profile(p)
    m = ModelRecord('openai','m','APPROVED',1,('low','medium','high'),'f'*64,1,2)
    repo.save_model(m)
    q = Qualification('openai','m',m.capability_fingerprint,p.profile_id,p.evaluation_identity_sha256,'GRAMMAR_ANALYSIS','NOT_QUALIFIED',None,0.1,1.0,'HIGH','LOW','MEASURED',0.01,'2026-08-31T00:00:00Z','e'*64)
    repo.save_qualification(q)
    bundle = Publisher(repo, authority_id='a', publication_epoch=1, output_paths=[]).publish(actor='ADMIN')
    qual = bundle['qualifications'][0]
    assert qual['minimum_reasoning'] is None
    assert qual['minimum_native_reasoning'] is None


def test_routine_reasoning_uses_tier_class_not_provider_names():
    tiers=(ReasoningTier('off',0,None,'OFF'),ReasoningTier('basic',10,'low','ROUTINE'),ReasoningTier('extreme',40,'high','PREMIUM'))
    m=ModelRecord('other','m','APPROVED',1,('off','basic','extreme'),'x',1,1,reasoning_tiers=tiers,tier_mapping_revision=1)
    assert m.routine_reasoning() == ('basic',)
