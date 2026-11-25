"""Comprueba por SSH el servicio propio en loopback y guarda evidencia sin credenciales."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8000);a=p.parse_args()
    code='''import json,subprocess,urllib.request,urllib.error
report={'url_local':'http://127.0.0.1:LOCAL_PORT','ssh':'OK','endpoints':{}}
for path in ('/docs','/health','/precios/actual','/precios?combustible=diesel&desde=2026-10-01&hasta=2026-11-30&limit=2','/modelo/metricas','/prediccion?combustible=super','/prediccion?combustible=regular','/prediccion?combustible=diesel','/prediccion?combustible=super&modo=vigente','/prediccion?combustible=regular&modo=vigente','/prediccion?combustible=diesel&modo=vigente','/prediccion/historica/semanas?fuente=mem','/prediccion/historica?combustible=super&fuente=mem','/prediccion/historica?combustible=regular&fuente=mem','/prediccion/historica?combustible=diesel&fuente=mem','/','/ui-assets/styles.css','/ui-assets/app.js','/ui-assets/favicon.svg','/proyecto/resumen','/entregables/informe','/entregables/presentacion','/entregables/resumen','/entregables/arquitectura'):
 try:
  with urllib.request.urlopen(report['url_local']+path,timeout=20) as r:
   body=r.read();result={'status':r.status}
   if 'json' in r.headers.get('Content-Type',''):result['body']=json.loads(body)
 except urllib.error.HTTPError as exc:result={'status':exc.code,'body':json.loads(exc.read())}
 report['endpoints'][path]=result
report['http_status']=report['endpoints']['/health']['status'];report['health']=report['endpoints']['/health'].get('body',{})
project=['docker','compose','--env-file','/home/cc3105-03/gasolina-equipo-05/api/.env','-p','cc3105-03-equipo05','-f','/home/cc3105-03/gasolina-equipo-05/api/compose.yaml']
cid=subprocess.run(project+['ps','-q','api'],capture_output=True,text=True,check=True).stdout.strip()
if not cid:raise RuntimeError('No se encontró el contenedor propio')
output=subprocess.run(['docker','inspect','--format','{{json .HostConfig.PortBindings}}\\n{{json .HostConfig.RestartPolicy}}\\n{{json .State.Status}}\\n{{json .Config.User}}',cid],capture_output=True,text=True,check=True).stdout.splitlines()
report['contenedor']={'port_bindings':json.loads(output[0]),'restart_policy':json.loads(output[1]),'estado':json.loads(output[2]),'usuario':json.loads(output[3])}
print(json.dumps(report,ensure_ascii=False,indent=2))
'''.replace('LOCAL_PORT',str(a.port))
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/proyecto_ed25519'),'-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=yes','cc3105-03@165.22.137.8','python3 -'],input=code,text=True,capture_output=True,check=True)
    data=json.loads(result.stdout);(ROOT/'output/resultado_droplet.json').write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data,ensure_ascii=False,indent=2))
