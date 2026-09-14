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

    @property
    def manifests(self):
        return sorted(self._manifests.values(), key=lambda item: (item.order, item.name.lower()))

    def get(self, module_id: str) -> ModuleManifest | None:
        return self._manifests.get(module_id)

    def discover(self):
        import ledgerone.modules as modules_package

        for info in pkgutil.iter_modules(modules_package.__path__):
            if info.name.startswith("_"):
                continue
            package_name = f"ledgerone.modules.{info.name}"
            package = importlib.import_module(package_name)
            manifest_module = importlib.import_module(f"{package_name}.manifest")
            manifest = getattr(manifest_module, "MANIFEST")
            self._manifests[manifest.id] = manifest
            self._packages[manifest.id] = package

    def register_blueprints(self, app):
        for manifest in self.manifests:
            package = self._packages[manifest.id]
            package.register(app)

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
