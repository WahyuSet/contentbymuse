import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import DictLoader, Environment, StrictUndefined, UndefinedError
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Format, PromptTemplate, PromptVersion
from app.domain.llm_outputs import OUTPUT_MODELS
from app.providers.base import Message

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            meta = yaml.safe_load(text[3:end]) or {}
            body = text[end + 4 :].lstrip("\n")
            return meta, body
    return {}, text


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _field_type_name(annotation) -> str:
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation).replace("typing.", "")


def output_contract(model: type[BaseModel]) -> str:
    """Kontrak output untuk prompt, dibangkitkan dari model Pydantic (Spec §3)."""
    lines = ["Respond with a single JSON object, no other text, with these fields:"]
    for name, field in model.model_fields.items():
        lines.append(_contract_line(name, field, indent=""))
        nested = _nested_model(field.annotation)
        if nested is not None:
            for sub_name, sub in nested.model_fields.items():
                lines.append(_contract_line(sub_name, sub, indent="  - "))
    return "\n".join(lines)


def _nested_model(annotation) -> type[BaseModel] | None:
    args = getattr(annotation, "__args__", ())
    for arg in args:
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def _contract_line(name, field, indent: str) -> str:
    parts = [f"{indent}- {name}: {_field_type_name(field.annotation)}"]
    constraints = []
    for meta in field.metadata:
        if getattr(meta, "min_length", None) is not None:
            constraints.append(f"min {meta.min_length} chars")
        if getattr(meta, "max_length", None) is not None:
            constraints.append(f"max {meta.max_length} chars")
        if getattr(meta, "pattern", None):
            constraints.append(f"pattern {meta.pattern}")
    if constraints:
        parts.append("(" + ", ".join(constraints) + ")")
    if field.description:
        parts.append(f"— {field.description}")
    return " ".join(parts)


@dataclass
class RenderedPrompt:
    task: str
    messages: list[Message]
    version_id: str
    temperature: float
    max_tokens: int
    output_model: type[BaseModel] | None


def _scan_files(root: Path):
    """Hasil: daftar (key, kind, path, file_version)."""
    found = []
    tasks_dir = root / "tasks"
    if tasks_dir.exists():
        for task_dir in sorted(tasks_dir.iterdir()):
            for path in sorted(task_dir.glob("v*.md")):
                match = re.match(r"v(\d+)\.md$", path.name)
                found.append((task_dir.name, "task", path, int(match.group(1))))
    blocks_dir = root / "blocks"
    if blocks_dir.exists():
        for path in sorted(blocks_dir.glob("*.md")):
            found.append((f"block.{path.stem}", "block", path, None))
    for kind, folder in (("category", "categories"), ("format", "formats")):
        folder_path = root / folder
        if folder_path.exists():
            for path in sorted(folder_path.glob("*.md")):
                found.append((f"{kind}.{path.stem}", kind, path, None))
    return found


async def sync_prompts(session: AsyncSession, root: Path | None = None) -> dict:
    """Sinkronkan file prompt ke DB (Spec §6.2) dan kategori/format (§2.1)."""
    root = root or PROMPTS_ROOT
    files = _scan_files(root)
    templates: dict[str, PromptTemplate] = {}
    versions_created = 0
    version_counters: dict[str, int] = {}
    newest_file: dict[str, tuple[int, str]] = {}
    for key, kind, path, file_version in files:
        text = path.read_text(encoding="utf-8")
        meta, _body = parse_frontmatter(text)
        digest = content_hash(text)
        if key not in templates:
            template = (
                await session.execute(
                    select(PromptTemplate).where(PromptTemplate.key == key)
                )
            ).scalar_one_or_none()
            if template is None:
                template = PromptTemplate(key=key, kind=kind)
                session.add(template)
                await session.flush()
            templates[key] = template
        template = templates[key]
        existing = (
            await session.execute(
                select(PromptVersion).where(
                    PromptVersion.template_id == template.id,
                    PromptVersion.content_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            # Nomor versi adalah urutan di DB, bukan nomor di file: mengedit file
            # di tempat (alur §6.2) membuat baris versi baru tanpa tabrakan unik.
            if template.id not in version_counters:
                current_max = (
                    await session.execute(
                        select(func.max(PromptVersion.version)).where(
                            PromptVersion.template_id == template.id
                        )
                    )
                ).scalar_one_or_none() or 0
                version_counters[template.id] = current_max + 1
            version_no = version_counters[template.id]
            version_counters[template.id] += 1
            session.add(
                PromptVersion(
                    template_id=template.id,
                    version=version_no,
                    source="builtin",
                    content=text,
                    frontmatter=meta,
                    content_hash=digest,
                )
            )
            versions_created += 1
        order = file_version if file_version is not None else int(meta.get("version", 1))
        if key not in newest_file or order >= newest_file[key][0]:
            newest_file[key] = (order, digest)
        if kind in ("category", "format"):
            await _sync_catalog_row(session, kind, path.stem, meta, template)
    await session.flush()
    for key, template in templates.items():
        active = None
        if template.active_version_id:
            active = await session.get(PromptVersion, template.active_version_id)
        if active is None or active.source == "builtin":
            digest = newest_file[key][1]
            target = (
                await session.execute(
                    select(PromptVersion).where(
                        PromptVersion.template_id == template.id,
                        PromptVersion.content_hash == digest,
                    )
                )
            ).scalar_one()
            template.active_version_id = target.id
    await session.flush()
    categories = (
        await session.execute(select(Category))
    ).scalars().all()
    formats = (await session.execute(select(Format))).scalars().all()
    return {
        "templates": len(templates),
        "versions": versions_created,
        "categories": len(categories),
        "formats": len(formats),
    }


async def _sync_catalog_row(session, kind: str, slug: str, meta: dict, template) -> None:
    model = Category if kind == "category" else Format
    row = (
        await session.execute(select(model).where(model.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        row = model(slug=slug, name=str(meta.get("name", slug)))
        session.add(row)
    row.name = str(meta.get("name", row.name))
    row.description = str(meta.get("description", ""))
    if kind == "category":
        row.fact_check = str(meta.get("fact_check", "normal"))
    row.prompt_template_id = template.id
    await session.flush()


class PromptService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _active_version(self, key: str) -> PromptVersion:
        template = (
            await self._session.execute(
                select(PromptTemplate).where(PromptTemplate.key == key)
            )
        ).scalar_one_or_none()
        if template is None or template.active_version_id is None:
            raise ValueError(
                f"Prompt '{key}' belum tersinkron. Jalankan sinkronisasi prompt saat startup."
            )
        version = await self._session.get(PromptVersion, template.active_version_id)
        if version is None:
            raise ValueError(f"Versi aktif prompt '{key}' tidak ditemukan.")
        return version

    async def active_body(self, key: str) -> str:
        version = await self._active_version(key)
        _meta, body = parse_frontmatter(version.content)
        return body

    async def render(self, task: str, inputs: dict) -> RenderedPrompt:
        version = await self._active_version(task)
        meta, body = parse_frontmatter(version.content)
        output_model = None
        context = dict(inputs)
        if meta.get("output"):
            output_model = OUTPUT_MODELS.get(str(meta["output"]))
            if output_model is None:
                raise ValueError(f"Model output '{meta['output']}' tidak dikenal.")
            context["output_contract"] = output_contract(output_model)
        block_rows = (
            await self._session.execute(
                select(PromptTemplate).where(PromptTemplate.kind == "block")
            )
        ).scalars()
        loader_map = {}
        for block in block_rows:
            if block.active_version_id:
                block_version = await self._session.get(
                    PromptVersion, block.active_version_id
                )
                if block_version is not None:
                    _m, block_body = parse_frontmatter(block_version.content)
                    name = block.key.removeprefix("block.")
                    loader_map[f"blocks/{name}.md"] = block_body
        env = Environment(
            loader=DictLoader(loader_map), undefined=StrictUndefined, autoescape=False
        )
        system_text, user_text = _split_sections(body)
        try:
            messages = []
            if system_text.strip():
                messages.append(
                    Message(role="system", content=env.from_string(system_text).render(context))
                )
            messages.append(
                Message(role="user", content=env.from_string(user_text).render(context))
            )
        except UndefinedError as exc:
            raise ValueError(f"Variabel prompt tidak dikenal: {exc.message}") from exc
        return RenderedPrompt(
            task=task,
            messages=messages,
            version_id=version.id,
            temperature=float(meta.get("temperature", 0.8)),
            max_tokens=int(meta.get("max_tokens", 4000)),
            output_model=output_model,
        )


def _split_sections(body: str) -> tuple[str, str]:
    system_match = re.search(r"^## \[system\]\s*$", body, flags=re.MULTILINE)
    user_match = re.search(r"^## \[user\]\s*$", body, flags=re.MULTILINE)
    if system_match and user_match and user_match.start() > system_match.end():
        return (
            body[system_match.end() : user_match.start()].strip(),
            body[user_match.end() :].strip(),
        )
    return "", body.strip()


_FLOOR_LINE = (
    "The character stands on a simple flat ground line near the lower third "
    "of the frame."
)


async def compose_image_prompt(session, style, scene) -> str:
    """Prompt gambar final §4.8: render template image.compose (bukan LLM).

    Perapian gaya 6p diterapkan sejak v1 di sini: spasi style_text dirapikan,
    jangkar maskot diakhiri tepat satu titik, dan kalimat garis lantai hanya
    untuk visual_type character/environment.
    """
    style_text = " ".join((style.style_text or "").split())
    anchor = ""
    if scene.include_mascot and style.mascot_anchor:
        anchor = style.mascot_anchor.strip().rstrip(".").strip() + "."
    floor_line = (
        _FLOOR_LINE if scene.visual_type in ("character", "environment") else ""
    )
    rendered = await PromptService(session).render(
        "image.compose",
        {
            "style_text": style_text,
            "mascot_anchor": anchor,
            "visual_prompt": scene.visual_prompt,
            "visual_type": scene.visual_type,
            "floor_line": floor_line,
        },
    )
    text = "\n".join(message.content for message in rendered.messages)
    lines = [line.strip() for line in text.splitlines()]
    lines = [
        line
        for line in lines
        if line and line not in ("## [system]", "## [user]")
    ]
    return "\n".join(lines)
