"""Prepara una publicación local verificable; no afirma haber escrito tablas remotas."""
import argparse,csv,json,sys,uuid
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.predictor import train_predictor,forecast,build_tables,today_gt,horizon_for_next_week
from src.silver import clean_photos

def build(destination,as_of=None):
    as_of=as_of or today_gt().isoformat();release=uuid.uuid4().hex
    directory=Path(destination)/'releases'/release;directory.mkdir(parents=True)
    with (ROOT/'data/ocr_review_flags.csv').open(newline='') as stream:
        flags={(r['foto_origen'],r['combustible']):r['motivo'] for r in csv.DictReader(stream)}
    photos=json.loads((ROOT/'output/ocr_completo.json').read_text())
    reference_path=ROOT/'output/referencias_ocr_revisadas.json'
    if reference_path.exists():references=json.loads(reference_path.read_text())
    elif (ROOT/'data/evaluacion_ocr_confirmada.csv').exists():
        with (ROOT/'data/evaluacion_ocr_confirmada.csv').open(newline='') as stream:references=list(csv.DictReader(stream))
    else:references=[]
    from src.ocr_evaluation import evaluate
    validation=evaluate(photos,references)
    accepted,rejected=clean_photos(photos['resultados'],flags,as_of,references)
    accepted.to_csv(directory/'silver_fotos.csv',index=False);rejected.to_csv(directory/'silver_rejected.csv',index=False)
    sources={'mem':pd.read_csv(ROOT/'data/external/mem/precios_normalizados.csv').to_dict('records'),'fotos':accepted.to_dict('records')}
    frames={name:[] for name in ('precio_semanal','variacion_semanal','features_modelo')};predictions=[];metrics=[];blocked={};reports={}
    for source,rows in sources.items():
        horizon=horizon_for_next_week(rows,as_of) if source=='mem' else 1
        weekly,features,data=build_tables(rows,as_of=as_of,horizon_weeks=horizon)
        quality='FUENTE_OFICIAL_RETROSPECTIVA' if source=='mem' else 'OCR_CANDIDATO_PENDIENTE_VALIDACION_HUMANA'
        for name,frame in [('precio_semanal',weekly),('features_modelo',features),('variacion_semanal',features[['semana','combustible','precio_promedio','precio_anterior','cambio_1w','variacion_pct','direccion','semana_cerrada']])]:
            frame=frame.copy();frame['fuente']=source;frame['estado_calidad']=quality;frames[name].append(frame)
        try:model,report,tables=train_predictor(rows,as_of=as_of,horizon_weeks=horizon)
        except ValueError as exc:
            reports[source]={'estado':'HISTORIA_INSUFICIENTE','detalle':str(exc)};continue
        forecasted,blocked[source]=forecast(model,tables['features_modelo'],as_of=as_of)
        for r in forecasted:r.update(fuente=source,estado_calidad=quality)
        predictions.extend(forecasted)
        reports[source]=report
        metrics.append({'fuente':source,'fecha_corte':as_of,'modelo':report['modelo'],'accuracy':report['modelo_test']['accuracy'],'macro_f1':report['modelo_test']['macro_f1'],'baseline_accuracy':report['baseline_test']['accuracy'],'baseline_macro_f1':report['baseline_test']['macro_f1'],'n_prueba':report['modelo_test']['n'],'estado_calidad':quality,'horizonte_semanas':horizon,'detalle_json':json.dumps(report)})
    manifest={'version':1,'release':release,'fecha_corte':as_of,'fuente_default':'mem','origen':'PREPARACION_LOCAL_NO_PUBLICACION_REMOTA','validacion_ocr':'MUESTRA_HUMANA_20_FOTOS_COMPLETA' if validation['cumple_minimo_20_fotos'] else 'PENDIENTE_REVISION_20_FOTOS','predicciones_bloqueadas':blocked,'tablas':{}}
    frames={name:pd.concat(parts,ignore_index=True) for name,parts in frames.items()}
    frames['predicciones']=pd.DataFrame(predictions,columns=['combustible','semana','semana_datos','prediccion','probabilidad','direccion_real','fecha_emision','fuente','estado_calidad','horizonte_semanas','antiguedad_datos_dias'])
    frames['metricas_modelo']=pd.DataFrame(metrics)
    for name,frame in frames.items():
        target=directory/(name+'.parquet');frame.to_parquet(target,index=False)
        if name in ('precio_semanal','variacion_semanal','predicciones','metricas_modelo'):manifest['tablas'][name]=[str(target.relative_to(destination))]
    (directory/'metricas_completas.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    Path(destination,'current.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'manifest':str(Path(destination,'current.json')),'aceptados_fotos':len(accepted),'rechazados_fotos':len(rejected),'predicciones_vigentes':len(predictions),'bloqueadas':blocked,'origen':manifest['origen']},ensure_ascii=False))
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',type=Path,default=ROOT/'output/api_local');p.add_argument('--as-of',default=today_gt().isoformat());a=p.parse_args();build(a.destination,a.as_of)
