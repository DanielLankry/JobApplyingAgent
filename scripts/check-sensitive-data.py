#!/usr/bin/env python3
"""Check tracked source and filenames without printing detected values (stdlib only)."""
from __future__ import annotations
import argparse
import collections
import json
import math
import pathlib
import re
import subprocess
import sys

BINARY_EXTENSIONS = {'.png','.jpg','.jpeg','.gif','.webp','.ico','.pdf','.docx','.xlsx','.zip','.gz','.whl','.exe','.dll','.pyc','.pkl','.pickle','.joblib','.pt','.pth','.onnx','.npy','.npz','.parquet','.woff','.woff2','.ttf','.mp4','.mov','.mp3','.wav'}
CODE_EXTENSIONS = {'.py','.js','.jsx','.ts','.tsx','.java','.cs','.php','.json','.yaml','.yml','.toml','.ini','.cfg','.conf','.env','.sh','.ps1','.ipynb'}
ID_PATTERN = re.compile(r'(?<![A-Za-z0-9])\d{9}(?![A-Za-z0-9])')
IDENTITY_CONTEXT = re.compile(r'\b(?:student(?:[_ -]?id)?|identity|national.?id|personal.?id|id.number|group.members|authors?|submitted.by)\b|ת[.״\"]?ז|תעודת\s*זהות|מגיש|סטודנט', re.I)
NAMED_ID = re.compile(r'^\s*[-*]?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s*[-:|]\s*\d{9}\s*$')
PROVIDER_RULES = [
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----')),
    ('provider-api-key', re.compile(r'\bsk-(?:proj-|ant-(?:api\d+-)?|or-v1-)?[A-Za-z0-9_-]{20,}\b')),
    ('github-token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b')),
    ('aws-access-key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('huggingface-token', re.compile(r'\bhf_[A-Za-z0-9]{20,}\b')),
    ('slack-token', re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b')),
    ('telegram-bot-token', re.compile(r'\b\d{7,12}:[A-Za-z0-9_-]{30,}\b')),
    ('jwt-literal', re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')),
]
CREDENTIAL_URL = re.compile(r'\b(?:postgres(?:ql)?(?:\+\w+)?|mysql|mongodb(?:\+srv)?|redis|amqps?|https?)://([^:/\s\"\x27]+):([^@/\s\"\x27]+)@[^/\s\"\x27]+',re.I)
LITERAL = re.compile(r'\b([A-Za-z_][\w.-]*(?:api[_-]?key|secret|token|password|passwd|pwd)[\w.-]*|(?:api[_-]?key|secret|token|password|passwd|pwd))[\"\x27]?\s*(?::\s*(?:str|string))?\s*[:=]\s*([\"\x27])([^\"\x27\r\n]{8,})\2',re.I)
ROBOFLOW_LITERAL = re.compile(r'(?:\bROBOFLOW_API_KEY[\"\x27]?\s*[:=]\s*|\bRoboflow\s*\(\s*api_key\s*=\s*)([\"\x27])([^\"\x27\r\n]{12,})\1',re.I)

def is_identity(value: str) -> bool:
    if len(value)!=9 or not value.isdigit() or len(set(value))==1:
        return False
    return sum(sum(divmod(int(c)*(1+i%2),10)) for i,c in enumerate(value))%10==0

def placeholder(value: str) -> bool:
    value=value.strip()
    return bool(re.search(r'(?i)your[_ -]|example|placeholder|dummy|redacted|removed|changeme|change-me|replace[_ -]|^\$\{|^\{|^<|^test[-_]|^audit[-_]',value)) or value.lower() in {'password','postgres','secret','username','user','pass','token','undefined','null'} or len(set(value))<4

def entropy(value: str) -> float:
    return -sum((n/len(value))*math.log2(n/len(value)) for n in collections.Counter(value).values())

def safe_path(path: str) -> str:
    path=ID_PATTERN.sub('[ID-REDACTED]',path)
    for _,rule in PROVIDER_RULES:
        path=rule.sub('[VALUE-REDACTED]',path)
    return path

def text_units(path: str, raw: bytes):
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError:return []
    if '\0' in text:return []
    if path.lower().endswith('.ipynb'):
        try:
            obj=json.loads(text)
            result=[]
            for i,cell in enumerate(obj.get('cells',[]),1):
                source=cell.get('source',[])
                result.append((f'cell {i} source',''.join(source) if isinstance(source,list) else str(source)))
                for j,out in enumerate(cell.get('outputs',[]),1):
                    for kind,value in [('text',out.get('text')),('traceback',out.get('traceback')),('plain',out.get('data',{}).get('text/plain'))]:
                        if value:result.append((f'cell {i} output {j} {kind}',''.join(value) if isinstance(value,list) else str(value)))
            return result
        except (ValueError,TypeError,AttributeError):
            # Still inspect malformed notebook source rather than silently skipping it.
            return [('text',text.replace('\\"','"'))]
    return [('text',text)]

def scan_file(path: str, raw: bytes):
    findings=[]
    def add(rule,line=0,location='filename'):
        finding={'rule':rule,'path':safe_path(path),'line':line,'location':location}
        if finding not in findings:findings.append(finding)
    for match in ID_PATTERN.finditer(path):
        if is_identity(match.group()):add('personal-id-in-filename')
    if pathlib.PurePosixPath(path).suffix.lower() in BINARY_EXTENSIONS:
        return findings
    code=pathlib.PurePosixPath(path).suffix.lower() in CODE_EXTENSIONS or pathlib.PurePosixPath(path).name.startswith('.env')
    for location,text in text_units(path,raw):
        lines=text.splitlines()
        for index,line in enumerate(lines):
            for rule,pattern in PROVIDER_RULES:
                for match in pattern.finditer(line):
                    if not placeholder(match.group()):add(rule,index+1,location)
            for match in CREDENTIAL_URL.finditer(line):
                if not placeholder(match.group(2)) and not re.search(r'\$\{|\{|\}',match.group()):add('credential-in-url',index+1,location)
            for match in ROBOFLOW_LITERAL.finditer(line):
                if not placeholder(match.group(2)):add('roboflow-literal-credential',index+1,location)
            if code and not re.search(r'(^|/)(?:tests?|__tests__|\.venv|venv|node_modules|vendor|third_party)(/|\.)',path,re.I):
                for match in LITERAL.finditer(line):
                    value=match.group(3)
                    if not placeholder(value) and not re.search(r'firebase|public|publishable',match.group(1),re.I) and entropy(value)>=3.2 and len(value)>=16:
                        add('literal-secret',index+1,location)
            # IDs need identity context; numeric datasets/lockfiles are not identity documents.
            if pathlib.PurePosixPath(path).suffix.lower() in {'.csv','.tsv','.lock'} or pathlib.PurePosixPath(path).name in {'package-lock.json','yarn.lock','uv.lock'}:
                continue
            context='\n'.join(lines[max(0,index-4):index+1])
            if IDENTITY_CONTEXT.search(context) or NAMED_ID.match(line):
                for match in ID_PATTERN.finditer(line):
                    if is_identity(match.group()):add('personal-id-in-content',index+1,location)
    return findings

def git(*args):
    result=subprocess.run(['git',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError('Git read failed')
    return result.stdout

def entries(mode: str,ref: str):
    if mode=='staged':
        paths=git('diff','--cached','--name-only','--diff-filter=ACMR','-z').split(b'\0')
        for path in paths:
            if path:yield path.decode('utf-8','replace'),git('show',':'+path.decode())
    elif mode=='worktree':
        paths=set(git('ls-files','-co','--exclude-standard','-z').split(b'\0'))
        for path in sorted(paths):
            if not path:continue
            filename=pathlib.Path(path.decode())
            if filename.is_symlink():continue
            if filename.is_file():yield path.decode('utf-8','replace'),filename.read_bytes()
    else:
        for record in git('ls-tree','-r','-z',ref).split(b'\0'):
            if not record:continue
            metadata,path=record.split(b'\t',1)
            _,kind,sha=metadata.split()
            if kind==b'blob':yield path.decode('utf-8','replace'),git('cat-file','blob',sha.decode())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--staged',action='store_true')
    group.add_argument('--worktree',action='store_true')
    parser.add_argument('--ref',default='HEAD')
    args=parser.parse_args()
    try:
        findings=[];count=0
        for path,raw in entries('staged' if args.staged else 'worktree' if args.worktree else 'ref',args.ref):
            count+=1;findings.extend(scan_file(path,raw))
        print(json.dumps({'files_checked':count,'findings':findings},ensure_ascii=True))
        return 1 if findings else 0
    except Exception:
        print(json.dumps({'error':'Sensitive-data check could not complete; no source values printed.'}))
        return 2

if __name__=='__main__':
    sys.exit(main())
