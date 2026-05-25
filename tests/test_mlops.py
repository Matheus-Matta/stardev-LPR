import pytest

from common.mlops import get_active_model, promote_model
from common.models import AIModelArtifact


@pytest.mark.django_db
def test_promote_model_deactivates_previous_model_of_same_kind():
    first = AIModelArtifact.objects.create(
        kind=AIModelArtifact.Kind.YOLO,
        version="lpr-v1.pt",
        storage_uri="/models/lpr-v1.pt",
        is_active=True,
    )
    second = AIModelArtifact.objects.create(
        kind=AIModelArtifact.Kind.YOLO,
        version="lpr-v2.pt",
        storage_uri="/models/lpr-v2.pt",
    )

    promote_model(second)
    first.refresh_from_db()
    second.refresh_from_db()

    assert not first.is_active
    assert second.is_active
    assert get_active_model(AIModelArtifact.Kind.YOLO) == second

