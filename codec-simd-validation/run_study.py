#!/usr/bin/env python3
"""Replay source-pinned SIMD numeric cases and retain observations."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
BEFORE = '1836f70c17cde142ac023da71a96ba9cc49c9213'
FIXED = '8e87b841b9374762a63af2a2e29246f701c1ccbd'
EXPECTED = {
    BEFORE: 'f41046a88fa59a3e26e96c1ed8c4d38b5ebca09238ce606a7a2120914705babc',
    FIXED: '3a475e000f7c3f40ed0ec6c928e5df5824f4190dc007e9a9f72ddd517bb5b51b'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def extract(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--case', choices=['x265'], default='x265')
    parser.add_argument('--x265-repo', type=Path, default=ROOT.parent/'s265/x265-psy-cost-12bit-review')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = []
    def command(argv, label, timeout=120, env=None):
        argv = [str(x) for x in argv]
        start = time.monotonic()
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
        commands.append({'label':label,'argv':argv,'returncode':result.returncode,'elapsed_seconds':time.monotonic()-start})
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        (out/(label+'.stdout')).write_bytes(result.stdout)
        (out/(label+'.stderr')).write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(f'{label} failed ({result.returncode}): '+result.stderr.decode(errors='replace')[-3000:])
        return result.stdout
    def git(commit, path):
        return command(['git','-C',args.x265_repo,'show',commit+':'+path], 'source-'+commit[:8]+'-'+Path(path).name)
    host_probe = ['/usr/bin/arch','-arm64','/usr/bin/uname','-m'] if platform.system() == 'Darwin' else ['uname','-m']
    host_machine = subprocess.check_output(host_probe, text=True).strip()
    if host_machine not in ('arm64','aarch64'):
        raise RuntimeError('An AArch64 host is required for this replay.')
    manifest = {'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'platform':platform.platform(),'machine':host_machine,'controller_machine':platform.machine(),'python':platform.python_version(),
                'protocol_sha256':sha((ROOT/'protocol.json').read_bytes()),
                'runner_sha256':sha(Path(__file__).read_bytes()),
                'harness_sha256':sha((ROOT/'harnesses/psy_cost.cpp').read_bytes()),'sources':[]}
    manifest['compiler'] = command(['/usr/bin/clang++','--version'],'compiler').decode()
    (out/'protocol.json').write_bytes((ROOT/'protocol.json').read_bytes())
    all_results = []
    for variant, commit in [('before',BEFORE),('fixed',FIXED)]:
        directory = out/variant
        directory.mkdir()
        sources = {}
        for path in ['source/common/aarch64/pixel-prim.cpp','source/common/aarch64/pixel-prim.h','source/common/aarch64/mem-neon.h','COPYING']:
            data=git(commit,path)
            blob=command(['git','-C',args.x265_repo,'rev-parse',commit+':'+path], 'blob-'+commit[:8]+'-'+Path(path).name).decode().strip()
            manifest['sources'].append({'variant':variant,'commit':commit,'path':path,'blob':blob,'sha256':sha(data)})
            (directory/Path(path).name).write_bytes(data)
            sources[path]=data.decode()
        assert sha(sources['source/common/aarch64/pixel-prim.cpp'].encode())==EXPECTED[commit]
        helper = sources['source/common/aarch64/pixel-prim.h']
        chunks = [extract(helper,'static inline void '+name+'(') for name in
                  ['sumsubq_s16','abssumsubq_s16','transpose_s16_s16x2','transpose_s16_s32x2','transpose_s16_s64x2']]
        chunks.insert(0,'template<int N>\n'+extract(sources['source/common/aarch64/mem-neon.h'],'static void inline load_u16x4xn('))
        kernel=extract(sources['source/common/aarch64/pixel-prim.cpp'],'static inline int calc_energy_4x4(')
        chunks.append(kernel)
        kernel_text='#include <arm_neon.h>\n#include <stdint.h>\n#define HIGH_BIT_DEPTH 1\nusing pixel = uint16_t;\nnamespace candidate {\n'+'\n\n'.join(chunks)+'\n}\n'
        (directory/'kernel.hpp').write_text(kernel_text)
        (directory/'harness.cpp').write_bytes((ROOT/'harnesses/psy_cost.cpp').read_bytes())
        manifest[variant+'_kernel_sha256']=sha(kernel.encode())
        for mode in ['normal','sanitized']:
            binary=directory/mode
            flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if mode=='sanitized' else []
            arch=['-arch','arm64'] if platform.system()=='Darwin' else []
            command(['/usr/bin/clang++',*arch,'-std=c++17','-O2','-g',*flags,directory/'harness.cpp','-o',binary],variant+'-'+mode+'-build')
            env=os.environ.copy()
            env.update(ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
            raw=command([binary],variant+'-'+mode+'-run',env=env)
            rows=[json.loads(line) for line in raw.decode().splitlines()]
            assert len(rows)==25
            for row in rows:
                assert row['oracle_disagreements']==row['input_mutations']==0
                if variant=='fixed' or row['depth']==10:
                    assert row['source_energy_mismatches']==row['recon_energy_mismatches']==row['cost_mismatches']==0,row
                if row['group'] in ['endpoints-near','exhaustive-near']:
                    assert row['cost_mismatches']==0,row
                row.update(variant=variant,mode=mode,classification='historical true defect replay',
                           detected=bool(row['cost_mismatches']),
                           mechanism='numeric differential' if row['cost_mismatches'] else 'no output mismatch')
                all_results.append(row)
            if variant=='before':
                witness=rows[0]['witness']
                assert witness['expected_cost']==67568 and witness['observed_cost']==2032
                assert sum(r['cost_mismatches'] for r in rows if r['depth']==12 and r['group'].startswith('exhaustive-'))==44800
                assert not (out/(variant+'-'+mode+'-run.stderr')).read_text().strip()
    by_key={}
    for row in all_results:
        key=(row['group'],row['depth'],row['seed'])
        fingerprint=(row['cases'],row['input_fnv1a64'])
        if key in by_key: assert by_key[key]==fingerprint
        by_key[key]=fingerprint
    manifest['completed_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest['paired_input_check']='all variants and sanitizer modes match input count and fingerprint'
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    results={'case':'x265-12bit-psy-reduction','status':'validated','rows':all_results,
             'limits':['Retrospective known defect.','Extracted production kernel with original helpers; not end-to-end encoding.','Harness timings include input generation, oracle and checking.','Sanitized mismatches are found by numeric oracle, not sanitizer diagnostics.']}
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps({'status':'validated','rows':len(all_results),'out':str(out),'paired_inputs':True}))

if __name__=='__main__':
    main()
