"""Cliente CLI con reintentos limitados para errores transitorios de conexión."""
import json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def api(method,path,body=None):
    command=['bash',str(ROOT/'scripts/databricks.sh'),'api',method,path,'--output','json']
    if body is not None:command+=['--json',json.dumps(body)]
    for attempt in range(6):
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        except subprocess.TimeoutExpired:
            if method.lower()!='get':raise RuntimeError('Timeout: comprobar el estado remoto antes de repetir una mutación')
            if attempt==5:raise
            time.sleep(2);continue
        if result.returncode==0:return json.loads(result.stdout) if result.stdout.strip() else {}
        error=result.stderr.strip()
        # DNS falla antes de enviar la solicitud: es seguro reintentar una mutación.
        safe_retry='no such host' in error or 'Temporary failure in name resolution' in error
        if method.lower()=='get':safe_retry=safe_retry or any(s in error for s in ('timed out','connection reset','503','502','429'))
        if not safe_retry or attempt==5:raise RuntimeError(error)
        time.sleep(2)
