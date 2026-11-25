"""Lectura y escritura del .env del servidor sin expandir ni registrar secretos."""
import os
import re
import shlex
import tempfile
from pathlib import Path


def parse_env(text):
    values={}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key,separator,value=line.partition('=')
        key=key.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key):
            raise ValueError('Formato .env no admitido; revisar nombres de variables')
        try:parts=shlex.split(value.strip(),comments=True,posix=True)
        except ValueError:raise ValueError('Formato .env no admitido para '+key) from None
        if len(parts)>1:raise ValueError('El valor debe estar entre comillas: '+key)
        values[key]=parts[0] if parts else ''
    return values


def update_env(text,updates):
    encoded={}
    for key,value in updates.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key):raise ValueError('Nombre de variable inválido')
        if value is None:encoded[key]=None;continue
        value=str(value)
        if any(c in value for c in ('\n','\r','\x00',"'")):
            raise ValueError('Formato de valor no admitido para '+key)
        encoded[key]=key+"='"+value+"'"
    lines=[];seen=set()
    for line in text.splitlines():
        key=line.partition('=')[0].strip()
        if not line.lstrip().startswith('#') and key in encoded:
            if key not in seen and encoded[key] is not None:lines.append(encoded[key])
            seen.add(key)
        else:lines.append(line)
    lines.extend(line for key,line in encoded.items() if key not in seen and line is not None)
    return '\n'.join(lines)+'\n'


def write_env_atomic(path,text):
    path=Path(path)
    if path.is_symlink():raise ValueError('El .env no debe ser un enlace simbólico')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.env.',delete=False) as stream:
            temporary=Path(stream.name);os.fchmod(stream.fileno(),0o600)
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
