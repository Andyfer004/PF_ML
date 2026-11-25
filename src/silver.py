"""Reglas y deduplicación de fotografías, independientes de Spark."""
from datetime import date
from decimal import Decimal,InvalidOperation
from collections import Counter
import pandas as pd
from src.price_quality import quarantine_review_flags

COLUMNS=['fecha','combustible','precio_q_galon','modalidad','ubicacion','foto_origen','fuente','estado_calidad','motivo_rechazo']
KEY=['fecha','ubicacion','combustible','modalidad']

def extraction_summary(source_photos,accepted,rejected):
    """Las fotos con algún rechazo pueden también tener precios aceptados."""
    photos=set(source_photos)
    good=set(accepted.foto_origen)
    bad=set(rejected.foto_origen)
    reasons=Counter(rejected.motivo_rechazo)
    return {'fotos_procesadas':len(photos),
            'fotos_con_precios_aceptados':len(photos & good),
            'fotos_sin_precios_aceptados':len(photos-good),
            'fotos_con_algun_rechazo':len(photos & bad),
            'fotos_con_aceptados_y_rechazados':len(photos & good & bad),
            'registros_aceptados':len(accepted),'registros_rechazados':len(rejected),
            'rechazos_por_motivo':[{'motivo_rechazo':reason,'registros':n,
                'fotos':int(rejected.loc[rejected.motivo_rechazo==reason,'foto_origen'].nunique())}
                for reason,n in sorted(reasons.items(),key=lambda item:(-item[1],item[0]))]}

def clean_photos(rows,flags,as_of,references=None):
    cutoff=date.fromisoformat(str(as_of));records=[]
    reviewed={r['foto_origen']:r for r in (references or []) if r.get('revisor','').strip() and r.get('confirmado_equipo','').lower()=='true'}
    for r in quarantine_review_flags(rows,flags):
        reasons=list(r.get('motivos_revision',[]));observed=r.get('fecha');value=None
        try:
            observed=date.fromisoformat(str(observed)[:10])
            if observed>cutoff:reasons.append('FECHA_FUTURA')
        except (ValueError,TypeError):
            observed=None;reasons.append('FECHA_INVALIDA')
        if r.get('combustible') not in ('super','regular','diesel'):reasons.append('COMBUSTIBLE_FUERA_CATALOGO')
        try:
            value=Decimal(str(r.get('precio_q_galon')))
            if not value.is_finite() or not Decimal('10')<=value<=Decimal('80'):raise ValueError('rango')
        except (InvalidOperation,ValueError,TypeError):
            value=None;reasons.append('PRECIO_AUSENTE_O_FUERA_RANGO')
        reference=reviewed.get(r['foto_origen'])
        if reference and r.get('combustible') in ('super','regular','diesel'):
            manual=reference.get('precio_'+r['combustible']+'_manual','')
            if not manual:reasons.append('REVISION_HUMANA_ILEGIBLE')
            elif value is not None and abs(value-Decimal(manual))>Decimal('.02'):
                reasons.append('DISCREPA_REFERENCIA_HUMANA')
        records.append({'fecha':observed.isoformat() if observed else None,'combustible':r.get('combustible','no_identificado'),'precio_q_galon':str(value) if value is not None else None,'modalidad':r.get('modalidad') or 'no_identificada','ubicacion':r.get('ubicacion') or 'no_identificada','foto_origen':r['foto_origen'],'fuente':'fotos','estado_calidad':'OCR_CANDIDATO_PENDIENTE_VALIDACION_HUMANA','motivo_rechazo':'|'.join(sorted(set(reasons)))})
    frame=pd.DataFrame(records,columns=COLUMNS)
    accepted=frame[frame.motivo_rechazo==''].copy();rejected=frame[frame.motivo_rechazo!=''].copy()
    if not accepted.empty:
        conflict=accepted.groupby(KEY).precio_q_galon.transform('nunique')>1
        bad=accepted[conflict].copy();bad['motivo_rechazo']='PRECIOS_EN_CONFLICTO_MISMA_LLAVE'
        rejected=pd.concat([rejected,bad],ignore_index=True)
        accepted=accepted[~conflict].sort_values('foto_origen').drop_duplicates(KEY)
    # No admite dos candidatos del mismo combustible en una foto.
    if frame.duplicated(['foto_origen','combustible']).any():raise ValueError('Candidatos repetidos por foto y combustible')
    return accepted,rejected
