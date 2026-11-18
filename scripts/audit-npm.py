"""Fail on unknown npm advisories; disclose one narrowly scoped unfixed dev advisory."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT/'apps/desktop'
# No upstream fix on 2026-11-18. Recheck upstream; never allow this in runtime deps.
KNOWN_DEV_ADVISORY = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf'


def main():
    npm = 'npm.cmd' if sys.platform == 'win32' else 'npm'
    result = subprocess.run([npm,'audit','--json'],cwd=FRONTEND,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8')
    try:
        data = json.loads(result.stdout)
    except ValueError:
        print('npm audit did not return a report; check registry/network access.');return 1
    if data.get('error') or result.returncode not in (0,1):
        print('npm audit failed; vulnerability status is unknown.');return 1
    lock = json.loads((FRONTEND/'package-lock.json').read_text(encoding='utf8'))
    unknown = []
    known = set()
    for package,entry in data.get('vulnerabilities',{}).items():
        dev_only = all(lock['packages'].get(node,{}).get('dev',False) for node in entry.get('nodes',[])) and bool(entry.get('nodes'))
        for advisory in entry.get('via',[]):
            if not isinstance(advisory,dict):continue
            if advisory.get('url')==KNOWN_DEV_ADVISORY and dev_only:
                known.add(advisory['url'])
            else:
                unknown.append((package,advisory.get('url','unknown'),entry['severity']))
    for package,url,severity in unknown:print(package,severity,url)
    for url in sorted(known):print('KNOWN UNFIXED DEV-ONLY FINDING:',url,'— not a clean full dependency audit; see docs/SECURITY_REVIEW.md')
    print('Unknown/non-dev advisory findings:',len(unknown))
    return 1 if unknown else 0


if __name__=='__main__':
    sys.exit(main())
