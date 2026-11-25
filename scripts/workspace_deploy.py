"""Importa solo archivos del proyecto al directorio propio de Databricks."""
import base64,json,subprocess,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST='/Users/fue22944@uvg.edu.gt/PF-ML'

import sys
sys.path.insert(0,str(ROOT))
from src.databricks_client import api

if __name__=='__main__':
    for name in ('','/src','/data'):api('post','/api/2.0/workspace/mkdirs',{'path':DEST+name})
    notebooks=['01_bronze','02_silver','03_gold','03_revision_manual','04_publicar_api']
    for name in notebooks:
        directory=ROOT/'pipelines' if name in ('01_bronze','02_silver','03_gold') else ROOT/'pipelines/auxiliares'
        api('post','/api/2.0/workspace/import',{'path':DEST+'/'+name,'format':'SOURCE','language':'PYTHON','overwrite':True,'content':base64.b64encode((directory/f'{name}.py').read_bytes()).decode()})
    files=[(p,'src/'+p.name) for p in (ROOT/'src').glob('*.py') if p.name not in ('gas_pipeline.py','external_data.py')]
    files += [(ROOT/'data'/name,'data/'+name) for name in ('ocr_layout_templates.json','ocr_review_flags.csv')]
    files += [(ROOT/'data/external/mem/precios_diarios_2026.xlsx','data/precios_diarios_2026.xlsx'),(ROOT/'data/evaluacion_ocr_manual.csv','evaluacion_ocr_manual.csv')]
    # Caché derivada de fotos autorizadas; nunca es referencia humana.
    from sys import path
    path.insert(0,str(ROOT))
    from src.lakehouse import code_signature
    report_path=ROOT/'output/ocr_completo.json'
    if report_path.exists():
        report=json.loads(report_path.read_text())
    else:report={}
    # No atribuir a una versión nueva resultados producidos por código anterior.
    if report.get('firma_codigo')==code_signature(ROOT):
        seed=ROOT/'output/ocr_seed.json'
        seed.write_text(json.dumps({'firma_codigo':report['firma_codigo'],'motor_origen':'Extracción local con firma de código comprobada','fotos':report['fotos_detalle']},ensure_ascii=False))
        files.append((seed,'ocr_seed.json'))
    reviewed=ROOT/'data/evaluacion_ocr_confirmada.csv'
    if reviewed.exists():
        with reviewed.open(newline='',encoding='utf-8') as stream:references=list(csv.DictReader(stream))
        if not all(r.get('revisor') and r.get('confirmado_equipo','').lower()=='true' for r in references):raise ValueError('Referencias sin confirmar')
        target=ROOT/'output/referencias_para_workspace.json';target.write_text(json.dumps(references,ensure_ascii=False,indent=2))
        files.append((target,'referencias_ocr_revisadas.json'))
    for source,target in files:
        print('Importando '+target,flush=True)
        api('post','/api/2.0/workspace/import',{'path':DEST+'/'+target,'format':'RAW','overwrite':True,'content':base64.b64encode(source.read_bytes()).decode()})
    print(json.dumps({'notebooks':notebooks,'archivos':len(files),'destino':DEST}))
