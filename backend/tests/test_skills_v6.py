"""W6 Skills Studio — resolution, lifecycle, reconcile, import hardening.

Covers the spec's done-when list: scoped listing, precedence
(agent-local > global > built-in), assignment bounds, publish gating,
pinned revisions surviving mid-run publishes, promote preserving history,
legacy migration, and repo-archive import hardening (draft-only).
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from agentos.models.agent import Agent
from agentos.models.execution_manifest import ExecutionManifest
from agentos.models.skill import Skill, SkillRevision
from agentos.skills import importer, reconcile, service, validate
from agentos.skills.builtins import BUILTIN_SKILLS
from agentos.skills.importer import ImportRejected
from agentos.skills.resolution import pinned_dir, resolve_effective_skills, skill_pins
from agentos.skills.service import SkillError


def _write_skill(root: Path, name: str, description: str = "a skill", body: str = "Body.") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def _zip_bytes(files: dict[str, bytes | str], symlink: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = 0o120777 << 16  # unix symlink
            zf.writestr(info, content)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Patch all four skill roots into tmp_path."""
    import agentos.config as cfg

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    store = tmp_path / "skills-store"
    drafts = tmp_path / "skills-drafts"
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setattr(cfg.settings, "skills_dir", skills_dir)
    monkeypatch.setattr(cfg.settings, "skills_store_root", store)
    monkeypatch.setattr(cfg.settings, "skills_drafts_root", drafts)
    monkeypatch.setattr(cfg.settings, "workspace_root", ws)
    return tmp_path


@pytest.fixture
async def agent(db):
    a = Agent(id="agent-1", name="Caber", enabled=True)
    db.add(a)
    await db.flush()
    return a


# ---------------------------------------------------------------------------
# Reconcile + resolution
# ---------------------------------------------------------------------------


class TestReconcile:
    async def test_seeds_builtins_as_published_revisions(self, db, env):
        _write_skill(env / "skills", "pdf", "PDF handling")
        monkey = pytest.MonkeyPatch()
        monkey.setattr(reconcile, "BUILTIN_SKILLS", {"pdf"})

        await reconcile.reconcile_skills(db)
        await db.commit()

        skill = await db.scalar(select(Skill).where(Skill.name == "pdf"))
        assert skill is not None
        assert skill.scope == "built-in"
        assert skill.status == "published"
        rev = await db.scalar(
            select(SkillRevision).where(SkillRevision.id == skill.current_revision_id)
        )
        assert rev is not None
        assert rev.revision_number == 1
        monkey.undo()

    async def test_migrates_legacy_dir_to_global_store(self, db, env, monkeypatch):
        _write_skill(env / "skills", "pdf", "shipped builtin")
        _write_skill(env / "skills", "my-thing", "legacy user import")
        monkeypatch.setattr(reconcile, "BUILTIN_SKILLS", {"pdf"})

        await reconcile.reconcile_skills(db)
        await db.commit()

        skill = await db.scalar(select(Skill).where(Skill.name == "my-thing"))
        assert skill.scope == "global"
        assert skill.status == "published"
        # Dir was MOVED out of skills/ into the store.
        assert not (env / "skills" / "my-thing").exists()
        rev = await db.scalar(
            select(SkillRevision).where(SkillRevision.id == skill.current_revision_id)
        )
        store_dir = env / "skills-store" / rev.storage_path
        assert (store_dir / "SKILL.md").is_file()

    async def test_indexes_agent_local_workspace_dirs(self, db, env, agent):
        _write_skill(env / "workspaces" / agent.id / "skills", "release-notes")

        await reconcile.reconcile_skills(db)
        await db.commit()

        row = await db.scalar(
            select(Skill).where(Skill.name == "release-notes", Skill.scope == "agent-local")
        )
        assert row is not None
        assert row.owner_agent_id == agent.id
        assert row.status == "published"

    async def test_builtin_manifest_matches_shipped_dirs(self):
        """skills/ contents must equal the manifest — drift means update both."""
        repo_skills = Path(__file__).resolve().parents[2] / "skills"
        actual = {d.name for d in repo_skills.iterdir() if d.is_dir()}
        assert actual == set(BUILTIN_SKILLS)


class TestResolution:
    async def test_builtin_global_local_scopes_resolve(self, db, env, agent, monkeypatch):
        _write_skill(env / "skills", "pdf", "shipped")
        monkeypatch.setattr(reconcile, "BUILTIN_SKILLS", {"pdf"})
        await reconcile.reconcile_skills(db)

        # Global skill via service.publish of a draft.
        draft = await service.import_draft(
            db,
            name="res-tool",
            source_dir=_write_skill(env / "tmp-g", "res-tool"),
            owner_agent_id=None,
        )
        await service.publish(db, draft, scope="global", availability="all")
        # Agent-local live skill.
        _write_skill(env / "workspaces" / agent.id / "skills", "mine")
        await db.commit()

        resolved = {s.name: s for s in await resolve_effective_skills(db, agent.id)}
        assert resolved["pdf"].scope == "built-in"
        assert resolved["res-tool"].scope == "global"
        assert resolved["mine"].scope == "agent-local"
        assert resolved["mine"].pin.startswith("live:")
        assert resolved["pdf"].pin.startswith("rev:")

    async def test_local_shadows_global_shadows_builtin(self, db, env, agent, monkeypatch):
        _write_skill(env / "skills", "pdf", "builtin pdf")
        monkeypatch.setattr(reconcile, "BUILTIN_SKILLS", {"pdf"})
        await reconcile.reconcile_skills(db)

        g = await service.import_draft(
            db, name="pdf", source_dir=_write_skill(env / "tmp", "pdf", "global pdf")
        )
        await service.publish(db, g, scope="global", availability="all")
        _write_skill(env / "workspaces" / agent.id / "skills", "pdf", "local pdf")
        await db.commit()

        resolved = {s.name: s for s in await resolve_effective_skills(db, agent.id)}
        # Local wins; both shadowed scopes recorded.
        assert resolved["pdf"].scope == "agent-local"
        assert resolved["pdf"].description == "local pdf"
        assert set(resolved["pdf"].shadows) == {"global", "built-in"}

        # For an agent with no local copy, global wins over built-in.
        other = Agent(id="agent-2", name="Other", enabled=True)
        db.add(other)
        await db.flush()
        resolved2 = {s.name: s for s in await resolve_effective_skills(db, other.id)}
        assert resolved2["pdf"].scope == "global"
        assert resolved2["pdf"].shadows == ["built-in"]

    async def test_assignment_bounds_global_visibility(self, db, env, agent):
        g = await service.import_draft(
            db, name="secret-sauce", source_dir=_write_skill(env / "tmp", "secret-sauce")
        )
        await service.publish(db, g, scope="global", availability="selected", agent_ids=[agent.id])
        other = Agent(id="agent-2", name="Other", enabled=True)
        db.add(other)
        await db.flush()

        names_a = {s.name for s in await resolve_effective_skills(db, agent.id)}
        names_b = {s.name for s in await resolve_effective_skills(db, other.id)}
        assert "secret-sauce" in names_a
        assert "secret-sauce" not in names_b

    async def test_disabled_and_draft_not_resolved(self, db, env, agent):
        await service.import_draft(db, name="wip", source_dir=_write_skill(env / "tmp", "wip"))
        g = await service.import_draft(db, name="off", source_dir=_write_skill(env / "tmp2", "off"))
        await service.publish(db, g, scope="global")
        await service.set_status(db, g, "disabled")
        await db.commit()

        names = {s.name for s in await resolve_effective_skills(db, agent.id)}
        assert "wip" not in names
        assert "off" not in names

    async def test_pinned_revision_survives_mid_run_publish(self, db, env, agent):
        g = await service.import_draft(
            db, name="evolving", source_dir=_write_skill(env / "tmp", "evolving", body="v1")
        )
        await service.publish(db, g, scope="global")
        await db.commit()

        # Run pins rev1.
        run_id = "run-1"
        resolved = {s.name: s for s in await resolve_effective_skills(db, agent.id)}
        pins = skill_pins(list(resolved.values()))
        db.add(
            ExecutionManifest(
                id="m-1",
                run_id=run_id,
                skill_revision_ids=json.dumps(pins),
            )
        )
        await db.flush()

        # Publish rev2 — changes bytes on disk under a NEW rev dir.
        new_src = _write_skill(env / "tmp", "evolving", body="v2")
        (new_src / "SKILL.md").write_text("---\nname: evolving\ndescription: a skill\n---\n\nv2\n")
        rev2 = await service.publish(db, g, scope="global")
        await db.commit()
        assert rev2.revision_number == 2

        # Fresh resolution sees rev2…
        resolved2 = {s.name: s for s in await resolve_effective_skills(db, agent.id)}
        assert resolved2["evolving"].revision_id == rev2.id
        # …but the run pinned to rev1 still serves rev1's bytes.
        pinned = await pinned_dir(db, resolved2["evolving"], run_id)
        assert (pinned / "SKILL.md").read_text().endswith("v1\n")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_promote_preserves_history_and_scope_change(self, db, env, agent):
        _write_skill(env / "workspaces" / agent.id / "skills", "pdf-x")
        draft = Skill(
            name="pdf-x", scope="agent-local", owner_agent_id=agent.id, status="published"
        )
        db.add(draft)
        await db.flush()
        r1 = await service.publish(db, draft, scope="agent-local")
        await service.promote(db, draft)
        await db.commit()

        assert draft.scope == "global"
        assert draft.owner_agent_id is None
        revs = (
            (await db.execute(select(SkillRevision).where(SkillRevision.skill_id == draft.id)))
            .scalars()
            .all()
        )
        assert {r.revision_number for r in revs} == {r1.revision_number, 2}

    async def test_publish_cleans_draft_dir(self, db, env, agent):
        draft = await service.create_draft(db, name="tidy", owner_agent_id=agent.id)
        ddir = service.draft_dir(draft)
        assert ddir.is_dir()
        (ddir / "SKILL.md").write_text("---\nname: tidy\ndescription: clean\n---\n\nbody\n")
        await service.publish(db, draft, scope="global")
        await db.commit()
        assert not ddir.exists()
        assert (env / "skills-store" / draft.id / "rev-1" / "SKILL.md").is_file()

    async def test_global_name_collision_rejected(self, db, env):
        a = await service.import_draft(db, name="dup", source_dir=_write_skill(env / "a", "dup"))
        await service.publish(db, a, scope="global")
        b = await service.import_draft(db, name="dup", source_dir=_write_skill(env / "b", "dup"))
        with pytest.raises(SkillError, match="already exists"):
            await service.publish(db, b, scope="global")

    async def test_purge_blocked_by_active_run_pin(self, db, env, agent):
        g = await service.import_draft(
            db, name="pinned", source_dir=_write_skill(env / "t", "pinned")
        )
        rev = await service.publish(db, g, scope="global")
        await service.set_status(db, g, "archived")
        from agentos.models.contact import Contact
        from agentos.models.run import Run

        db.add(
            Contact(
                id="c-1",
                channel="dashboard_chat",
                bot_id=agent.id,
                external_user_id="op",
            )
        )
        db.add(
            Run(
                id="run-1",
                agent_id=agent.id,
                session_id="s",
                contact_id="c-1",
                status="running",
            )
        )
        db.add(
            ExecutionManifest(
                id="m-1",
                run_id="run-1",
                skill_revision_ids=json.dumps({"pinned": f"rev:{rev.id}"}),
            )
        )
        await db.flush()
        with pytest.raises(SkillError, match="active run"):
            await service.purge(db, g)

    async def test_detail_usage_lists_runs_pinning_revision(self, db, env, agent):
        """B6 regression: usage rows serialize Run.started_at — Run has
        no created_at column; touching it raised AttributeError → 500."""
        from types import SimpleNamespace

        from agentos.api.skills import skill_detail
        from agentos.models.contact import Contact
        from agentos.models.run import Run

        g = await service.import_draft(db, name="used", source_dir=_write_skill(env / "t", "used"))
        rev = await service.publish(db, g, scope="global")
        db.add(
            Contact(
                id="c-1",
                channel="dashboard_chat",
                bot_id=agent.id,
                external_user_id="op",
            )
        )
        db.add(
            Run(
                id="run-used-1",
                agent_id=agent.id,
                session_id="s",
                contact_id="c-1",
                status="completed",
                trigger="user_message",
            )
        )
        db.add(
            ExecutionManifest(
                id="m-1",
                run_id="run-used-1",
                skill_revision_ids=json.dumps({"used": f"rev:{rev.id}"}),
            )
        )
        await db.flush()

        detail = await skill_detail(g.id, operator=SimpleNamespace(id="op"), db=db)
        usage = detail["usage"]
        assert len(usage) == 1
        assert usage[0]["run_id"] == "run-used-1"
        assert usage[0]["status"] == "completed"
        assert usage[0]["created_at"]  # ISO timestamp from Run.started_at

    async def test_builtin_cannot_purge(self, db, env, monkeypatch):
        _write_skill(env / "skills", "pdf")
        monkeypatch.setattr(reconcile, "BUILTIN_SKILLS", {"pdf"})
        await reconcile.reconcile_skills(db)
        skill = await db.scalar(select(Skill).where(Skill.name == "pdf"))
        await service.set_status(db, skill, "archived")
        with pytest.raises(SkillError, match="built-in"):
            await service.purge(db, skill)


# ---------------------------------------------------------------------------
# Import hardening
# ---------------------------------------------------------------------------


class TestImporter:
    def test_candidates_from_monorepo_zip(self):
        archive = _zip_bytes(
            {
                "repo-main/skills/one/SKILL.md": "---\nname: one\ndescription: 1\n---\n\nx\n",
                "repo-main/skills/one/scripts/s.py": "print(1)\n",
                "repo-main/skills/two/SKILL.md": "---\nname: two\ndescription: 2\n---\n\nx\n",
                "repo-main/README.md": "# repo\n",
            }
        )
        cands = importer.skill_candidates(archive)
        assert {c["name"] for c in cands} == {"one", "two"}
        assert {c["path"] for c in cands} == {"repo-main/skills/one/", "repo-main/skills/two/"}

    def test_traversal_rejected(self, tmp_path):
        archive = _zip_bytes(
            {"SKILL.md": "---\nname: x\ndescription: d\n---\n\n", "../evil": "nope"}
        )
        with pytest.raises(ImportRejected, match="traversal"):
            importer.extract_skill_subtree(archive, "", tmp_path / "out")

    def test_symlink_rejected(self, tmp_path):
        # Craft a zip with a real symlink entry.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: x\ndescription: d\n---\n\n")
            info = zipfile.ZipInfo("link")
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "target")
        with pytest.raises(ImportRejected, match="symlink"):
            importer.extract_skill_subtree(buf.getvalue(), "", tmp_path / "out")

    def test_macosx_junk_skipped(self, tmp_path):
        archive = _zip_bytes(
            {
                "SKILL.md": "---\nname: x\ndescription: d\n---\n\n",
                "__MACOSX/._SKILL.md": "junk",
                "._hidden": "junk",
            }
        )
        importer.extract_skill_subtree(archive, "", tmp_path / "out")
        files = [f.name for f in (tmp_path / "out").rglob("*") if f.is_file()]
        assert files == ["SKILL.md"]

    async def test_imported_skills_land_as_drafts(self, db, env, agent):
        archive = _zip_bytes(
            {
                "repo/s1/SKILL.md": "---\nname: s1\ndescription: one\n---\n\n",
                "repo/s2/SKILL.md": "---\nname: s2\ndescription: two\n---\n\n",
            }
        )
        for cand in importer.skill_candidates(archive):
            tmp = env / f"ext-{cand['name']}"
            importer.extract_skill_subtree(archive, cand["path"], tmp)
            skill = await service.import_draft(db, name=cand["name"], source_dir=tmp)
            assert skill.status == "draft"

        # Drafts are inert — resolution never sees them.
        names = {s.name for s in await resolve_effective_skills(db, agent.id)}
        assert "s1" not in names and "s2" not in names
        assert (env / "skills-drafts" / "s1" / "SKILL.md").is_file()

    def test_archive_url_normalization(self):
        assert importer.archive_url_for("https://github.com/o/r") == (
            "https://codeload.github.com/o/r/zip/HEAD"
        )
        assert importer.archive_url_for("https://github.com/o/r/tree/dev") == (
            "https://codeload.github.com/o/r/zip/dev"
        )
        assert (
            importer.archive_url_for("https://gitlab.com/grp/proj/-/tree/main")
            == "https://gitlab.com/grp/proj/-/archive/main/proj-main.zip"
        )
        assert importer.archive_url_for("https://x.example.com/a.zip") == (
            "https://x.example.com/a.zip"
        )
        assert importer.archive_url_for("o/r") == ("https://codeload.github.com/o/r/zip/HEAD")
        with pytest.raises(ImportRejected):
            importer.archive_url_for("http://github.com/o/r")  # https only


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_errors_and_warnings_split(self, tmp_path):
        good = _write_skill(tmp_path / "s", "good-skill", "desc")
        result = validate.validate_skill_dir(good)
        assert result["errors"] == []
        # license/compatibility missing → warnings only
        assert any("license" in w for w in result["warnings"])

    def test_name_dir_mismatch_and_missing_refs_are_errors(self, tmp_path):
        d = tmp_path / "dirx"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: other\ndescription: d\n---\n\nsee `scripts/missing.py`\n"
        )
        result = validate.validate_skill_dir(d)
        assert any("must match" in e for e in result["errors"])
        assert any("does not exist" in e for e in result["errors"])

    def test_unknown_capability_is_error(self, tmp_path):
        d = _write_skill(tmp_path / "s", "cap-user")
        (d / "SKILL.md").write_text(
            "---\nname: cap-user\ndescription: d\nallowed-tools: not_a_tool\n---\n\n"
        )
        result = validate.validate_skill_dir(
            d, known_capabilities={"read_file"}, granted_capabilities={"read_file"}
        )
        assert any("unknown capability" in e for e in result["errors"])

    def test_ungranted_capability_is_warning(self, tmp_path):
        d = _write_skill(tmp_path / "s", "cap-user")
        (d / "SKILL.md").write_text(
            "---\nname: cap-user\ndescription: d\nallowed-tools: terminal\n---\n\n"
        )
        result = validate.validate_skill_dir(
            d,
            known_capabilities={"terminal", "read_file"},
            granted_capabilities={"read_file"},
        )
        assert any("not granted" in w for w in result["warnings"])
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# W11 regression — findings from the live test run (B7–B13)
# ---------------------------------------------------------------------------


class TestW11Regressions:
    async def test_duplicate_without_owner_lands_ownerless_draft(self, db, env):
        """B7: duplicate with owner_agent_id=None crashed joining None into
        the workspace path — ownerless duplicates go to data/skills-drafts/."""
        g = await service.import_draft(db, name="orig", source_dir=_write_skill(env / "o", "orig"))
        await service.publish(db, g, scope="global")

        dup = await service.duplicate(db, g, owner_agent_id=None)

        assert dup.status == "draft" and dup.owner_agent_id is None
        assert service.draft_dir(dup) == env / "skills-drafts" / "orig-copy"
        assert "name: orig-copy" in (service.draft_dir(dup) / "SKILL.md").read_text()

    async def test_archived_hidden_from_live_views(self, db, env, agent):
        """B8: archived rows leave every live view but stay reachable via
        view=archived (unarchive/purge need somewhere to live)."""
        from types import SimpleNamespace

        from agentos.api.skills import list_skills

        op = SimpleNamespace(id="op")
        g = await service.import_draft(db, name="arch", source_dir=_write_skill(env / "a", "arch"))
        await service.publish(db, g, scope="global")
        await service.set_status(db, g, "archived")

        names = {s["name"] for s in (await list_skills(view="all", operator=op, db=db))["skills"]}
        assert "arch" not in names
        archived = (await list_skills(view="archived", operator=op, db=db))["skills"]
        assert {s["name"] for s in archived} == {"arch"}

    async def test_promote_retires_live_dir(self, db, env, agent):
        """B9: promote snapshots the live dir into the rev then removes it —
        a leftover live dir kept shadowing the global row for its owner."""
        _write_skill(env / "workspaces" / agent.id / "skills", "pro")
        s = Skill(name="pro", scope="agent-local", owner_agent_id=agent.id, status="published")
        db.add(s)
        await db.flush()
        live = service.live_local_dir(s)
        await service.publish(db, s, scope="agent-local")
        await service.promote(db, s)
        await db.commit()

        assert s.scope == "global" and s.owner_agent_id is None
        assert not live.exists()
        resolved = {x.name: x for x in await resolve_effective_skills(db, agent.id)}
        assert resolved["pro"].pin.startswith("rev:")

    async def test_second_global_publish_revalidates_cleanly(self, db, env):
        """B10: republishing a governed skill used to fail — validation
        compared the frontmatter name to the `rev-N` storage dir."""
        from types import SimpleNamespace

        from agentos.api.skills import PublishBody, publish_skill

        g = await service.import_draft(
            db, name="re-pub", source_dir=_write_skill(env / "p", "re-pub")
        )
        op = SimpleNamespace(id="op")
        body = PublishBody(scope="global", availability="all")
        await publish_skill(g.id, body, op, db)
        again = await publish_skill(g.id, body, op, db)
        assert again["revision"] == 2

    def test_validate_revision_dir_uses_expected_name(self, tmp_path):
        """B10 at the validator: `rev-N` dirs pass when expected_name given,
        still fail without it."""
        d = tmp_path / "rev-3"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: foo\ndescription: d\n---\n\nbody\n", encoding="utf-8"
        )
        assert any("must match" in e for e in validate.validate_skill_dir(d)["errors"])
        ok = validate.validate_skill_dir(d, expected_name="foo")
        assert not any("must match" in e for e in ok["errors"])

    def test_anchor_fragment_refs_resolve(self, tmp_path):
        """B13: `references/x.md#heading` must check x.md, not the literal
        path including the fragment."""
        d = _write_skill(tmp_path / "s", "anch", "d", body="see `references/x.md#sec`")
        (d / "references").mkdir()
        (d / "references" / "x.md").write_text("# x\n", encoding="utf-8")
        result = validate.validate_skill_dir(d)
        assert result["errors"] == []
