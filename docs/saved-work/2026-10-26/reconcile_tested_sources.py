from pathlib import Path
import json,hashlib,re
R=Path('/home/user');O=R/'verification/release-execution-2026-10-26';ledger={}
for folder in ['pending-implementation-2026-10-26','remaining-implementation-2026-10-26']:
 for x in json.loads((R/'verification'/folder/'changed-files.json').read_text()):ledger[x['path']]=(folder,x)
results=[]
for name,(folder,row) in ledger.items():
 p=R/name;current=p.read_bytes() if p.exists() else None
 if current is not None and hashlib.sha256(current).hexdigest()==row['afterSHA256']:continue
 known=False
 for b in ['pending-implementation-2026-10-26/before','remaining-implementation-2026-10-26/before','remaining-implementation-2026-10-26/before-strict-ack','target-route-fix-2026-10-24/before','release-execution-2026-10-26/drift-before']:
  q=R/'verification'/b/name
  if current is not None and q.exists() and current==q.read_bytes():known=True
 assert current is None or known,'Unknown source drift; stopped: '+name
 patch=(R/'verification'/folder/'CHANGES.patch').read_text().splitlines(True)
 i=next(i for i,l in enumerate(patch) if l=='+++ b/'+name+'\n');j=i+1
 while j<len(patch) and not patch[j].startswith('--- '):j+=1
 before=R/'verification'/folder/'before'/name;source=before.read_text().splitlines(True) if before.exists() else [];new=[];pos=0;k=i+1
 while k<j:
  m=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',patch[k]);assert m,(name,patch[k]);start=int(m.group(1));at=start-1 if start else 0;new.extend(source[pos:at]);pos=at;k+=1
  while k<j and not patch[k].startswith('@@ '):
   line=patch[k]
   if line.startswith(' '):assert source[pos]==line[1:];new.append(line[1:]);pos+=1
   elif line.startswith('-'):assert source[pos]==line[1:];pos+=1
   elif line.startswith('+'):new.append(line[1:])
   elif not line.startswith('\\'):raise AssertionError('Malformed retained patch')
   k+=1
 new.extend(source[pos:]);data=''.join(new).encode();assert hashlib.sha256(data).hexdigest()==row['afterSHA256'],name
 if current is not None:
  checkpoint=O/'fresh-integrity-before'/name;checkpoint.parent.mkdir(parents=True,exist_ok=True)
  if checkpoint.exists():assert checkpoint.read_bytes()==current
  else:checkpoint.write_bytes(current)
 assert (p.read_bytes() if p.exists() else None)==current,'Concurrent source drift; stopped'
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);results.append({'path':name,'previousKnownVersion':known,'previousMissing':current is None,'restoredSHA256':row['afterSHA256']})
for name,(_,row) in ledger.items():assert hashlib.sha256((R/name).read_bytes()).hexdigest()==row['afterSHA256'],name
(O/'fresh-reconciliation.json').write_text(json.dumps({'restored':results,'combinedScopedFilesVerified':len(ledger)},indent=2)+'\n')
print('Reconciled',len(results),'known earlier/missing files; verified',len(ledger),'combined scoped SHA256 hashes. No unknown drift overwritten.')
