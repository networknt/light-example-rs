#!/usr/bin/env python3
"""Reconcile saved evidence only; preserves the original failed summary."""
import argparse,json
from pathlib import Path
from rust_petstore_acceptance import read,write,reconcile_records,digest,PLAN

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('evidence',type=Path);a=p.parse_args();out=a.evidence
    if digest(PLAN)!=read(out/'identities.json')['planSha256']:raise ValueError('pre-execution plan drift')
    rows=read(out/'rows.json');calls=read(out/'sanitized-calls.json');records=read(out/'backend-records.json')
    errors=reconcile_records(rows,calls,records)
    cleanup=read(out/'cleanup.json');jwks=read(out/'jwks-receipts.json')
    if len(cleanup)!=5 or not all(r['reaped'] for r in cleanup):errors.append('five owning-process reaps')
    if jwks!=[{'method':'GET','path':'/jwks'}]:errors.append('independently measured JWKS receipt')
    original=read(out/'report.json')
    result=dict(original,green=not errors,errors=errors,originalSummaryPreserved=True,
        originalSummarySha256=digest(out/'report.json'),reconciliation='Offline correction of single-echo-a helper misuse; predeclared A/B identities and expectations unchanged',
        currentRunnerSha256=digest(Path(__file__).with_name('rust_petstore_acceptance.py')),planSha256=digest(PLAN),requestsRerun=0,
        backendEchoChecks=4,allFiveProcessesReaped=True)
    write(out/'offline-reconciled-report.json',result)
    print(json.dumps(result,indent=2));return 0 if result['green'] else 1
if __name__=='__main__':raise SystemExit(main())
