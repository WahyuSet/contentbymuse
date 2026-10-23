import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Category, ContentIdea, Project, PromptTemplate, PromptVersion, Provider


async def test_project_requires_topic_or_category(session):
    session.add(Project(title="Tanpa topik"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_project_defaults(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.commit()
    assert project.language == "id-ID"
    assert (project.target_min_s, project.target_max_s) == (0, 45)
    assert project.settings == {}


async def test_idea_batch_rows(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    session.add(
        ContentIdea(
            project_id=project.id,
            batch=1,
            position=1,
            title="Judul ide yang cukup panjang",
            job_id="01JTEST",
        )
    )
    await session.commit()


async def test_category_slug_unique(session):
    session.add(Category(slug="animals", name="Hewan"))
    await session.commit()
    session.add(Category(slug="animals", name="Duplikat"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_prompt_version_shape(session):
    template = PromptTemplate(key="ideas.from_topic", kind="task")
    session.add(template)
    await session.flush()
    version = PromptVersion(
        template_id=template.id,
        version=1,
        source="builtin",
        content="isi",
        frontmatter={},
        content_hash="abc",
    )
    session.add(version)
    await session.commit()
    template.active_version_id = version.id
    await session.commit()


async def test_provider_defaults(session):
    provider = Provider(name="Fake", capability="llm", adapter="fake")
    session.add(provider)
    await session.commit()
    assert provider.enabled is True and provider.quirks == {}
