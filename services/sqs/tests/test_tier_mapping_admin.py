from pathlib import Path
import pytest
from sage_sqs.admin import AdminApp
from sage_sqs.db import Database
from sage_sqs.domain import ModelRecord, ReasoningTier
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository
from sage_sqs.providers.openai_provider import load_openai_catalog, sync_provider_catalog


def app(tmp_path):
    repo=Repository(Database.open(tmp_path/'sqs.db'))
    return repo, AdminApp(repo,publisher=Publisher(repo,authority_id='a',publication_epoch=1,output_paths=[]))


def test_provider_catalog_proposes_mapping_but_admin_must_approve_it(tmp_path: Path):
    repo, admin=app(tmp_path)
    candidate=load_openai_catalog(Path('config/openai-provider.yml'))[0]
    sync_provider_catalog(repo,[candidate])
    model=repo.latest_model('openai',candidate.model_id)
    assert model.tier_mapping_approved is False
    assert any(x['category']=='TIER_MAPPING_REVIEW' for x in repo.list_attention())
    with pytest.raises(ValueError, match='TIER_MAPPING_NOT_APPROVED'):
        admin.approve_model(candidate.model_id)
    admin.approve_tier_mapping(candidate.model_id)
    admin.approve_model(candidate.model_id)
    assert repo.latest_model('openai',candidate.model_id).status=='APPROVED'


def test_admin_can_edit_provider_native_assignment_before_approval(tmp_path: Path):
    repo, admin=app(tmp_path)
    model=ModelRecord('other','m','REVIEW_REQUIRED',1,('basic','deep'),'f'*64,1,1,
        reasoning_tiers=(ReasoningTier('basic',10,'low','ROUTINE'),ReasoningTier('deep',20,'high','ROUTINE')),
        tier_mapping_approved=False)
    repo.save_model(model)
    edited=(ReasoningTier('basic',10,'medium','ROUTINE'),ReasoningTier('deep',20,'high','PREMIUM'))
    admin.approve_tier_mapping('m',provider_family='other',reasoning_tiers=edited)
    saved=repo.latest_model('other','m')
    assert saved.tier_mapping_approved is True
    assert saved.reasoning_tiers==edited
    assert saved.tier_mapping_revision==2
