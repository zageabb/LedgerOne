from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from ledgerone.extensions import db
from ledgerone.models.core import ModuleState


@dataclass(frozen=True)
class ModuleManifest:
    id: str
    name: str
    description: str
    icon: str = "box"
    order: int = 100
    route_endpoint: str | None = None
    api_prefix: str | None = None
    home_name: str | None = None
    professional_name: str | None = None
    default_enabled: bool = True
    always_on: bool = False
    home_visible: bool = True
    professional_visible: bool = True
    permissions: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    # Optional workflow integration. The adapter is stored as an import string instead
    # of a class reference so module discovery never has to import another domain package.
    workflow_entity_type: str | None = None
    workflow_adapter: str | None = None
    workflow_post_permission: str | None = None

    def display_name(self, mode: str) -> str:
        if mode == "home" and self.home_name:
            return self.home_name
        if mode == "professional" and self.professional_name:
            return self.professional_name
        return self.name


class ModuleRegistry:
    def __init__(self):
        self._manifests: dict[str, ModuleManifest] = {}
        self._packages: dict[str, object] = {}
        self._workflow_modules: dict[str, str] = {}
        self._workflow_adapters: dict[str, object] = {}

    @property
    def manifests(self):
        return sorted(self._manifests.values(), key=lambda item: (item.order, item.name.lower()))

    def get(self, module_id: str) -> ModuleManifest | None:
        return self._manifests.get(module_id)

    def discover(self):
        import ledgerone.modules as modules_package

        # App factories are created repeatedly in tests. Rebuild the lightweight lookup
        # indexes so stale adapters from an earlier app cannot leak into a new registry pass.
        self._workflow_modules.clear()
        self._workflow_adapters.clear()
        for info in pkgutil.iter_modules(modules_package.__path__):
            if info.name.startswith("_"):
                continue
            package_name = f"ledgerone.modules.{info.name}"
            package = importlib.import_module(package_name)
            manifest_module = importlib.import_module(f"{package_name}.manifest")
            manifest = getattr(manifest_module, "MANIFEST")
            self._manifests[manifest.id] = manifest
            self._packages[manifest.id] = package
            if manifest.workflow_entity_type:
                existing = self._workflow_modules.get(manifest.workflow_entity_type)
                if existing and existing != manifest.id:
                    raise RuntimeError(
                        f"Workflow entity type {manifest.workflow_entity_type!r} is declared by both "
                        f"{existing!r} and {manifest.id!r}"
                    )
                if not manifest.workflow_adapter or not manifest.workflow_post_permission:
                    raise RuntimeError(
                        f"Module {manifest.id!r} declares workflow entity "
                        f"{manifest.workflow_entity_type!r} without adapter/post permission"
                    )
                self._workflow_modules[manifest.workflow_entity_type] = manifest.id

    def register_blueprints(self, app):
        for manifest in self.manifests:
            package = self._packages[manifest.id]
            package.register(app)

    def workflow_manifest(self, entity_type: str | None) -> ModuleManifest | None:
        if not entity_type:
            return None
        module_id = self._workflow_modules.get(entity_type)
        return self._manifests.get(module_id) if module_id else None

    def workflow_adapter(self, entity_type: str | None):
        """Lazily load the adapter declared by the module that owns an entity type."""
        manifest = self.workflow_manifest(entity_type)
        if not manifest or not manifest.workflow_adapter:
            return None
        cached = self._workflow_adapters.get(entity_type)
        if cached is not None:
            return cached
        module_name, separator, attribute_name = manifest.workflow_adapter.partition(":")
        if not separator or not module_name or not attribute_name:
            raise RuntimeError(
                f"Invalid workflow adapter path {manifest.workflow_adapter!r} for module {manifest.id!r}"
            )
        module = importlib.import_module(module_name)
        adapter = getattr(module, attribute_name)
        self._workflow_adapters[entity_type] = adapter
        return adapter

    def ensure_org_states(self, organisation_id: str):
        for manifest in self.manifests:
            if manifest.always_on:
                continue
            state = ModuleState.query.filter_by(
                organisation_id=organisation_id, module_id=manifest.id
            ).first()
            if not state:
                db.session.add(
                    ModuleState(
                        organisation_id=organisation_id,
                        module_id=manifest.id,
                        enabled=manifest.default_enabled,
                    )
                )
        db.session.commit()

    def seed_module_defaults(self, organisation_id: str, module_id: str):
        package = self._packages.get(module_id)
        if package is None:
            return
        seed_defaults = getattr(package, "seed_defaults", None)
        if callable(seed_defaults):
            seed_defaults(organisation_id)

    def seed_org_defaults(self, organisation_id: str):
        """Seed defaults only for modules that are enabled for this organisation."""
        for manifest in self.manifests:
            if not self.is_enabled(organisation_id, manifest.id):
                continue
            self.seed_module_defaults(organisation_id, manifest.id)
        db.session.commit()

    def is_enabled(self, organisation_id: str | None, module_id: str) -> bool:
        manifest = self.get(module_id)
        if not manifest:
            return False
        if manifest.always_on:
            return True
        if not organisation_id:
            return False
        state = ModuleState.query.filter_by(
            organisation_id=organisation_id, module_id=module_id
        ).first()
        return manifest.default_enabled if state is None else state.enabled


module_registry = ModuleRegistry()
