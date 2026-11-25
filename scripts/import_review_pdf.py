"""Importa únicamente lecturas confirmadas por una persona desde el cuaderno PDF."""
import argparse,csv,json,sys,hashlib
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]

def extract(pdf):
    fields=PdfReader(pdf).get_fields() or {}
    def value(name):return str(fields.get(name,{}).get('/V','')).strip()
    references=[]
    with (ROOT/'data/evaluacion_ocr_manual.csv').open(newline='') as stream:sample=list(csv.DictReader(stream))
    for i,row in enumerate(sample):
        prefix=f'p{i:02d}_';checked=value(prefix+'confirmado') in ('/Yes','Yes','true')
        if not checked:continue
        name=Path(row['foto_origen']).name
        allowed={name,row['foto_origen'],row['foto_origen'].split('/img/',1)[-1]}
        if not value(prefix+'revisor') or value(prefix+'archivo') not in allowed:raise ValueError(f'{name}: falta revisor o confirmación exacta del archivo')
        result=dict(row,revisor=value(prefix+'revisor'),confirmado_equipo='true',observaciones=value(prefix+'observaciones'))
        for fuel in ('diesel','regular','super'):
            raw=value(prefix+fuel)
            if not raw:
                if not result['observaciones']:raise ValueError(f'{name}: explicar precios ilegibles en observaciones')
                result['precio_'+fuel+'_manual']='';continue
            number=Decimal(raw.replace(',','.'))
            if not number.is_finite() or not Decimal('10')<=number<=Decimal('80') or number.as_tuple().exponent < -2:raise ValueError(f'{name}: precio inválido')
            result['precio_'+fuel+'_manual']=str(number.quantize(Decimal('.01')))
        result['ubicacion_manual']=value(prefix+'ubicacion');result['modalidad_manual']=value(prefix+'modalidad')
        result['fecha_revision_utc']=datetime.now(timezone.utc).isoformat()
        result['referencia_origen']='revision_pdf_equipo'
        result['sha256_pdf']=hashlib.sha256(Path(pdf).read_bytes()).hexdigest() if Path(pdf).exists() else ''
        result['combustibles_ilegibles']=[fuel for fuel in ('diesel','regular','super') if not result.get('precio_'+fuel+'_manual')]
        references.append(result)
    return references

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf',type=Path);p.add_argument('--output',type=Path,default=ROOT/'output/referencias_ocr_revisadas.json');a=p.parse_args()
    result=extract(a.pdf);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'fotos_confirmadas':len(result),'archivo':str(a.output)}))
