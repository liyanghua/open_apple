"""Bounded, hash-validating closure of production evidence (read-only)."""
from __future__ import annotations
from collections.abc import Mapping
from pathlib import Path
from lib.production_evidence import file_sha256, project_file, read_object


def dependency_closure(root, record_path=None, *, document=None):
    dependencies, visiting, visited = {}, set(), set()
    containers = {'canonical_artifacts', 'review_dependencies', 'source_refs', 'evidence_refs'}

    def visit(ref, depth=0):
        if depth > 40 or len(dependencies) >= 4096:
            raise ValueError('Production dependency graph limit exceeded')
        expected = ref.get('sha256') if isinstance(ref, Mapping) else None
        name = ref.get('path') if isinstance(ref, Mapping) else ref
        path = project_file(root, name)
        name = path.relative_to(root.resolve()).as_posix()
        sha = file_sha256(path)
        if expected is not None and expected != sha:
            raise ValueError(f'Dependency hash mismatch: {name}')
        if isinstance(ref, Mapping) and any(key in ref for key in ('semantic_sha256', 'artifact_sha256')):
            from lib.artifact_hashing import verify_hashes
            artifact = read_object(root, name)
            if not verify_hashes(artifact).valid or any(ref[key] != artifact.get(key) for key in ('semantic_sha256', 'artifact_sha256') if key in ref):
                raise ValueError(f'Artifact dependency hash mismatch: {name}')
        if name in visiting:
            raise ValueError(f'Production dependency cycle: {name}')
        dependencies[name] = {'path': name, 'sha256': sha}
        if name in visited:
            return
        visiting.add(name)
        if path.suffix.lower() == '.json':
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Production JSON dependency exceeds size limit')
            doc = read_object(root, name)
            walk(doc, depth + 1)
            # Concrete public inputs are part of the approved rendered version.
            if 'footage' in doc and 'scenes' in doc:
                for value in doc['footage'].values():
                    local = 'public/' + value if (root / 'public' / value).is_file() else value
                    visit(local, depth + 1)
                if doc.get('logoSrc'):
                    local = 'public/' + doc['logoSrc'] if (root / 'public' / doc['logoSrc']).is_file() else doc['logoSrc']
                    visit(local, depth + 1)
                # Fonts are already visited as typed path+sha256 references by
                # walk(doc). Their browser src is a staged URL, not a source path.
        visiting.remove(name)
        visited.add(name)

    def walk(value, depth, string_refs=False):
        if depth > 80:
            raise ValueError('Production dependency nesting limit exceeded')
        if isinstance(value, Mapping):
            if 'path' in value and ('sha256' in value or string_refs):
                visit(value, depth)
                return
            for key, child in value.items():
                if key == 'category_profile_ref':
                    from lib.category_profile import load_category_profile_ref
                    load_category_profile_ref(Path(root), child)
                    name = child['path']
                    base = Path(__file__).resolve().parents[1] if name.startswith('config/category_profiles/') else Path(root)
                    path = (base / name).resolve()
                    dependencies['category_profile:' + name] = {'path': name, 'sha256': file_sha256(path)}
                    continue
                refs = key in containers or key.endswith('_ref') or key in {'baseline'}
                walk(child, depth + 1, string_refs or refs)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1, string_refs)
        elif string_refs and isinstance(value, str):
            visit(value, depth)

    if document is None:
        visit(record_path)
    else:
        walk(document, 0)
    return {key: dependencies[key] for key in sorted(dependencies)}
