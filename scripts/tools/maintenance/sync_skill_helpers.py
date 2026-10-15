"""Bundle canonical helpers and log rules into the independent development Skill."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-skill',type=Path,required=True)
    p.add_argument('--development-skill',type=Path,required=True)
    args=p.parse_args()
    src,dst=args.source_skill.resolve(),args.development_skill.resolve()
    if src==dst or not (src/'SKILL.md').is_file() or not (dst/'SKILL.md').is_file():
        p.error('specify two independent Skill roots containing SKILL.md')
    files={}
    for name in ('scripts/resolve_paths.ps1','scripts/setup_raw.ps1',
                 'references/maintain/maintain-log.md'):
        target=dst/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src/name,target)
        files[name]=sha256(target.read_bytes()).hexdigest()
    (dst/'bundled-helpers.json').write_text(json.dumps({
        'format_version':1,'canonical_package':'dst-wiki-skill',
        'files':files,'sync':'dst-toolbox/scripts/tools/maintenance/sync_skill_helpers.py'
    },indent=2)+'\n',encoding='utf-8')
    print('Bundled independent helpers; no runtime dependency on another Skill.')

if __name__=='__main__': main()
