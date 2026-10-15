"""Resolve external knowledge inputs, never infer them from the toolbox checkout."""
import json
from pathlib import Path

TOOLBOX = Path(__file__).resolve().parents[2]

def knowledge_root(value=None, config=None):
    if value is None:
        path = Path(config) if config else Path.home() / '.dst-wiki/config.json'
        if not path.is_file():
            raise ValueError('specify --knowledge-root or configure ~/.dst-wiki/config.json')
        value = json.loads(path.read_text(encoding='utf-8-sig')).get('knowledge_root')
    if not value or not Path(value).is_absolute():
        raise ValueError('knowledge_root must be an absolute path')
    root = Path(value).resolve()
    if not (root / 'wiki/index.md').is_file():
        raise ValueError(f'knowledge root must contain wiki/index.md: {root}')
    return root

def source_root(value=None, knowledge=None, config=None):
    return Path(value).resolve() if value is not None else knowledge_root(knowledge, config) / 'raw/current/scripts'

def catalog_root(catalog, value=None, knowledge=None):
    if value is not None:
        return Path(value).resolve()
    if catalog['revision']['scheme'] == 'fixture':
        # root_hint remains historical provenance, not a checkout-layout contract.
        return TOOLBOX / 'scripts/tests/fixtures/extraction'
    return source_root(knowledge=knowledge)
