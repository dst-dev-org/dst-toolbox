"""Rebuildable exact-key source index. Syntax references are not runtime dependencies."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root

REPO = Path(__file__).resolve().parents[3]
RELATIONS = ('call', 'component', 'event', 'prefab', 'target')


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def inside(root: Path, path: str) -> Path:
    if not path or any(c in path for c in '\\:') or any(p in ('', '.', '..') for p in path.split('/')):
        raise ValueError(f'unsafe relative path: {path}')
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'path escapes root: {path}')
    return target


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')


def shard_name(category: str, key: str) -> str:
    return 'shards/'+category+'/'+digest(key.encode('utf-8'))[:2]+'.json'


def checked_facts(facts: dict, source: bytes | None) -> tuple[dict, dict]:
    if facts.get('format_version') != '1.0.0' or facts.get('kind') != 'facts':
        raise ValueError('unsupported facts version/kind')
    anchors = {a['id']: a for a in facts['anchors']}
    symbols = {s['id']: s for s in facts['symbols']}
    if len(anchors) != len(facts['anchors']) or len(symbols) != len(facts['symbols']):
        raise ValueError('duplicate anchor/symbol IDs')
    if facts['coverage']['status'] == 'failed':
        if anchors or symbols or facts['records']:
            raise ValueError('failed input contains evidence')
        return anchors, symbols
    if source is None:
        raise ValueError('successful facts without readable source')
    source.decode('utf-8')
    lines = [-1]+[i for i, b in enumerate(source) if b == 10]
    for anchor in anchors.values():
        start, end = (anchor[k]['byte'] for k in ('start','end'))
        if not 0 <= start <= end <= len(source) or digest(source[start:end]) != anchor['sha256']:
            raise ValueError('anchor byte/hash mismatch')
        if anchor['source_id'] != 'dst' or anchor['path'] != facts['primary_file']:
            raise ValueError('anchor source mismatch')
        for point in ('start','end'):
            position = anchor[point]; byte = position['byte']
            line = bisect_right(lines, byte-1)
            if position['line'] != line or position['column'] != byte-lines[line-1]:
                raise ValueError('anchor position mismatch')
            if byte < len(source) and source[byte] & 0xC0 == 0x80:
                raise ValueError('anchor splits UTF-8 character')
    selection = facts['coverage']['selection']
    if set(selection['symbols']) != symbols.keys():
        raise ValueError('symbol coverage mismatch')
    for symbol in symbols.values():
        if symbol['anchor_id'] not in anchors or symbol['owner_id'] is not None and symbol['owner_id'] not in symbols:
            raise ValueError('symbol reference missing')
    record_ids = set()
    for record in facts['records']:
        if record['id'] in record_ids: raise ValueError('duplicate record ID')
        record_ids.add(record['id'])
        if record['anchor_id'] not in anchors or record['subject_symbol_id'] not in symbols or record['kind'] not in selection['record_kinds']:
            raise ValueError('record reference/selection mismatch')
        for guard in record['guards']:
            if guard['anchor_id'] not in anchors: raise ValueError('guard reference missing')
        data = record['data']
        for key in ('field_symbol_id','target_symbol_id'):
            if key in data and data[key] not in symbols: raise ValueError('record symbol missing')
        resolution = data.get('resolution')
        if resolution:
            state=resolution['state']; candidates=resolution['candidates']; target=resolution['symbol_id']
            if not set(candidates) <= symbols.keys(): raise ValueError('resolution candidate missing')
            if state == 'resolved' and (target not in symbols or candidates): raise ValueError('invalid resolved target')
            if state == 'unresolved' and (target is not None or candidates or not resolution['reason']): raise ValueError('invalid unresolved target')
            if state == 'ambiguous' and (target is not None or len(set(candidates)) < 2 or not resolution['reason']): raise ValueError('invalid ambiguity')
            if state not in ('resolved','unresolved','ambiguous'): raise ValueError('invalid resolution state')
    for diagnostic in facts['coverage']['diagnostics']:
        if diagnostic['anchor_id'] is not None and diagnostic['anchor_id'] not in anchors:
            raise ValueError('diagnostic anchor missing')
    return anchors, symbols


def build(snapshot: Path, source_root: Path) -> dict:
    snapshot=snapshot.resolve(); source_root=source_root.resolve()
    if snapshot.is_relative_to(source_root) or source_root.is_relative_to(snapshot):
        raise ValueError('snapshot overlaps source')
    index=snapshot/'source-index'
    if index.exists(): raise ValueError('index exists; use a fresh extraction directory')
    manifest=read_json(snapshot/'manifest.json'); report=read_json(snapshot/'coverage-report.json')
    if manifest.get('format_version') != '1.0.0' or manifest.get('kind') != 'manifest' or report.get('report_version') != 1:
        raise ValueError('unsupported manifest/report')
    sid=manifest['snapshot']['id']
    version=manifest['snapshot']['version']
    if version['scheme']=='steam-buildid' and (source_root.parent/'BUILD.txt').read_text(encoding='utf-8').strip()!=version['value']:
        raise ValueError('source build differs from snapshot')
    if report['snapshot_id'] != sid: raise ValueError('snapshot mismatch')
    results=report['results']; selected=report['input_scope']['selected_paths']
    if sorted(r['path'] for r in results) != sorted(set(selected)) or len(selected) != report['selected_files']:
        raise ValueError('selection mismatch')
    if report['failed_files'] != sum(r['status']=='failed' for r in results): raise ValueError('failed count mismatch')
    sources={s['id']:s for s in manifest['sources']}
    files={f['path']:f for f in sources['dst']['files']}
    if set(files) != {r['path'] for r in results if r['input_kind']=='utf8-source'}: raise ValueError('manifest input mismatch')
    buckets=defaultdict(list); inputs=[]; counts=Counter(); resolutions=Counter()
    for item in results:
        path=item['path']; source_file=inside(source_root,path)
        try: source=source_file.read_bytes()
        except OSError: source=None
        if (digest(source) if source is not None else None) != item['sha256']:
            raise ValueError(f'stale source: {path}')
        if source is not None and len(source) != item['bytes']: raise ValueError(f'input length mismatch: {path}')
        if path in files and files[path]['sha256'] != item['sha256']: raise ValueError(f'manifest hash mismatch: {path}')
        fact_path='facts/'+path+'.json'; fact_bytes=inside(snapshot,fact_path).read_bytes(); facts=json.loads(fact_bytes)
        if facts['snapshot_id'] != sid or facts['primary_file'] != path: raise ValueError('facts identity mismatch')
        if any(facts['coverage'][k] != item[k] for k in ('status','truncated','diagnostics')):
            raise ValueError('coverage report differs from facts')
        anchors,symbols=checked_facts(facts,source)
        if len(symbols) != item['symbols'] or len(facts['records']) != item['records']: raise ValueError('coverage counts differ')
        inputs.append({'path':path,'sha256':item['sha256'],'facts':fact_path,'facts_sha256':digest(fact_bytes),'status':item['status'],'truncated':item['truncated']})
        def location(anchor_id):
            a=anchors[anchor_id]
            return {'path':path,'line':a['start']['line'],'column':a['start']['column'],'start_byte':a['start']['byte'],'end_byte':a['end']['byte'],'sha256':a['sha256']}
        for symbol in symbols.values():
            counts['symbols']+=1
            if symbol['name']=='<chunk>': continue
            entry={**symbol,'source':location(symbol['anchor_id']),'coverage':item['status']}
            buckets['definition',symbol['name']].append(entry)
            buckets['definition',symbol['id']].append(entry)
        for record in facts['records']:
            counts[record['kind']]+=1
            data=record['data']; entry={'id':record['id'],'kind':record['kind'],'subject':record['subject_symbol_id'],'source':location(record['anchor_id']),'guards':[{'expression':g['expression'],'branch':g['branch'],'source':location(g['anchor_id'])} for g in record['guards']],'data':data,'coverage':item['status']}
            category={'call':'call','component_access':'component','event_emit':'event','event_listen':'event','prefab_registration':'prefab'}.get(record['kind'])
            if category: buckets[category,data['callee'] if category=='call' else data['literal_name'] or '<dynamic>'].append(entry)
            resolution=data.get('resolution')
            if resolution:
                resolutions[resolution['state']]+=1
                # Ambiguous candidates are lookup clues, retained with their state.
                for target in ([resolution['symbol_id']] if resolution['state']=='resolved' else resolution['candidates']):
                    buckets['target',target].append(entry)
    groups=defaultdict(dict)
    for (category,key),entries in buckets.items():
        entries.sort(key=lambda e:(e['source']['path'],e['source']['start_byte'],e['id']))
        groups[shard_name(category,key)][key]=entries
    shards={}
    for name,group in groups.items():
        write_json(index/name,group)
        shards[name]={'sha256':digest((index/name).read_bytes()),'keys':len(group)}
    metadata={'index_version':1,'kind':'source-index','snapshot_id':sid,'version':manifest['snapshot']['version'],'producer':manifest['producer'],
              'input_scope':report['input_scope'],'inputs':inputs,'counts':dict(counts),'resolutions':dict(resolutions),
              'coverage':dict(Counter(i['status'] for i in inputs)), 'failed_paths':[i['path'] for i in inputs if i['status']=='failed'],
              'truncated_paths':[i['path'] for i in inputs if i['truncated']], 'shards':shards,
              'manifest_sha256':digest((snapshot/'manifest.json').read_bytes()),'report_sha256':digest((snapshot/'coverage-report.json').read_bytes())}
    write_json(index/'index.json',metadata)
    return {k:metadata[k] for k in ('snapshot_id','counts','resolutions','coverage','failed_paths','truncated_paths')}


def query(snapshot: Path, source_root: Path, category: str, key: str, *, limit: int=5, path: str|None=None, kind: str|None=None, max_bytes: int=16000) -> dict:
    if category not in ('definition',*RELATIONS) or not 1<=limit<=20 or not 1024<=max_bytes<=64000:
        raise ValueError('invalid category/limit/budget')
    if len(key)>512 or path is not None and len(path)>512:
        raise ValueError('query key/path too long; use a shorter identifier')
    snapshot=snapshot.resolve(); index=snapshot/'source-index'; metadata=read_json(index/'index.json')
    if metadata.get('index_version')!=1: raise ValueError('unsupported index version')
    stale=[]
    if metadata['version']['scheme']=='steam-buildid':
        try: current_build=(source_root.parent/'BUILD.txt').read_text(encoding='utf-8').strip()
        except OSError: current_build=None
        if current_build!=metadata['version']['value']: stale.append('BUILD.txt')
    for filename,field in [('manifest.json','manifest_sha256'),('coverage-report.json','report_sha256')]:
        if digest((snapshot/filename).read_bytes()) != metadata[field]: stale.append(filename)
    for item in metadata['inputs']:
        try: current=digest(inside(source_root,item['path']).read_bytes())
        except OSError: current=None
        if current != item['sha256']: stale.append(item['path'])
    if metadata['input_scope'].get('selection_mode')=='full-scan':
        current={p.relative_to(source_root).as_posix() for p in source_root.rglob('*.lua')}
        if current != set(metadata['input_scope']['selected_paths']): stale.append('<source-file-set>')
    result={'query':{'category':category,'key':key,'path':path,'kind':kind},'snapshot_id':metadata['snapshot_id'],'version':metadata['version'],
            'coverage':{'selection_mode':metadata['input_scope'].get('selection_mode','explicit'),'selected_files':len(metadata['inputs']),'statuses':metadata['coverage'],
                        'failed_files':len(metadata['failed_paths']),'failed_paths':metadata['failed_paths'][:5],'failed_paths_truncated':len(metadata['failed_paths'])>5,
                        'source_truncated_files':len(metadata['truncated_paths']),'excluded_by_design':metadata['input_scope']['excluded_by_design']},
            'status':'stale' if stale else 'ok','stale_count':len(stale),'stale_paths':stale[:5],'total':0,'returned':0,'ambiguous':False,'truncated':False,'results':[],
            'note':'Syntax links only. Unresolved/dynamic references, partial/failed sources and filtered results cannot prove absence or runtime dependencies.'}
    def bounded(result):
        result.update(returned=len(result['results']),truncated=len(result['results'])<result['total'])
        while len(json.dumps(result,ensure_ascii=False).encode('utf-8'))+1>max_bytes:
            if result['results']:
                result['results'].pop();result.update(returned=len(result['results']),truncated=True)
            else:
                raise ValueError('budget too small for query/coverage metadata')
        return result
    if stale: return bounded(result)
    name=shard_name(category,key); descriptor=metadata['shards'].get(name)
    entries=[]
    if descriptor:
        raw=inside(index,name).read_bytes()
        if digest(raw)!=descriptor['sha256']: raise ValueError('index shard changed; rebuild index')
        group=json.loads(raw)
        if len(group)!=descriptor['keys']: raise ValueError('shard key count mismatch')
        entries=group.get(key,[])
    entries=[e for e in entries if (path is None or e['source']['path']==path) and (kind is None or e['kind']==kind)]
    relevant_paths={e['source']['path'] for e in entries}
    for item in metadata['inputs']:
        if item['path'] in relevant_paths and digest(inside(snapshot,item['facts']).read_bytes())!=item['facts_sha256']:
            raise ValueError('selected facts changed; rebuild index')
    result.update(total=len(entries),ambiguous=category=='definition' and len(entries)>1,status='ok' if entries else 'no-match')
    def compact(value):
        if isinstance(value,str) and len(value)>240: return {'text':value[:240],'truncated':True,'original_chars':len(value)}
        if isinstance(value,list): return [compact(v) for v in value]
        if isinstance(value,dict): return {k:compact(v) for k,v in value.items()}
        return value
    for entry in entries[:limit]:
        candidate=compact(entry)
        if len(json.dumps({**result,'results':result['results']+[candidate]},ensure_ascii=False).encode('utf-8'))>max_bytes: break
        result['results'].append(candidate)
    result.update(returned=len(result['results']),truncated=len(result['results'])<len(entries))
    return bounded(result)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('build','query'):
        p=sub.add_parser(command); p.add_argument('--snapshot-root',type=Path,required=True); p.add_argument('--source-root',type=Path); p.add_argument('--knowledge-root',type=Path)
        if command=='query':
            p.add_argument('category',choices=('definition',*RELATIONS));p.add_argument('key');p.add_argument('--limit',type=int,default=5)
            p.add_argument('--path');p.add_argument('--kind');p.add_argument('--max-bytes',type=int,default=16000)
    args=parser.parse_args()
    args.source_root=source_root(args.source_root,args.knowledge_root)
    value=build(args.snapshot_root,args.source_root) if args.command=='build' else query(args.snapshot_root,args.source_root,args.category,args.key,limit=args.limit,path=args.path,kind=args.kind,max_bytes=args.max_bytes)
    print(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    return 1 if value.get('status')=='stale' else 0


if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({'status':'error','message':str(error)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
