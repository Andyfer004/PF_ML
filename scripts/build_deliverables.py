"""Genera entregables PDF a partir de resultados comprobados; distingue preparación local y despliegue."""
import csv,io,json,sys,textwrap
from pathlib import Path
from PIL import Image,ImageOps
from pillow_heif import register_heif_opener
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor,white
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image as RLImage
from reportlab.lib import colors
ROOT=Path(__file__).resolve().parents[1]
NAVY=HexColor('#112d43');TEAL=HexColor('#087f8c');GRAY=HexColor('#526678');LIGHT=HexColor('#eef3f6')
register_heif_opener()
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyES',fontName='Helvetica',fontSize=11,leading=16,textColor=NAVY,spaceAfter=9))
styles.add(ParagraphStyle(name='HeadingES',fontName='Helvetica-Bold',fontSize=19,leading=24,textColor=NAVY,spaceAfter=15))
styles.add(ParagraphStyle(name='SmallES',fontName='Helvetica',fontSize=8,leading=11,textColor=GRAY,spaceAfter=6))
manifest=json.loads((ROOT/'output/api_local/current.json').read_text())
release=ROOT/'output/api_local/releases'/manifest['release']
metrics=json.loads((release/'metricas_completas.json').read_text())
# Preferir las métricas de los Parquet reales de Oro al preparar la entrega.
snapshot=ROOT/'output/api_oro_real'
if (snapshot/'current.json').exists():
 import pyarrow.parquet as pq
 real=json.loads((snapshot/'current.json').read_text())
 rows=[]
 for relative in real['tablas']['metricas_modelo']:
  path=(snapshot/relative).resolve()
  if not path.is_relative_to(snapshot.resolve()):raise ValueError('Métricas fuera del snapshot')
  rows.extend(pq.read_table(path).to_pylist())
 for source in ('mem','fotos'):
  candidates=[row for row in rows if row['fuente']==source]
  if candidates:metrics[source]=json.loads(max(candidates,key=lambda row:str(row['fecha_corte']))['detalle_json'])
 manifest=real
m=metrics['mem'];photo=metrics['fotos'];cutoff=manifest['fecha_corte']
current_predictions=m.get('predicciones',[])
forecast_text='Las predicciones se sirven solo cuando su semana objetivo sigue vigente.'
if current_predictions:
 p=current_predictions[0]
 forecast_text=f"El modelo usa la semana {p['semana_datos']} para pronosticar {p['semana']}, con horizonte {m['horizonte_semanas']} y antigüedad de {p['antiguedad_datos_dias']} días al emitir."
successful=[]
for file in (ROOT/'output/ejecuciones').glob('*.json'):
 try:
  record=json.loads(file.read_text())
  if record.get('ejecucion',{}).get('state',{}).get('result_state')=='SUCCESS':successful.append(record)
 except (ValueError,KeyError):pass
validation=json.loads((ROOT/'output/evaluacion_ocr_humana.json').read_text())
latest_run=max(successful,key=lambda r:r['ejecucion'].get('start_time',0)) if successful else {}
silver_snapshot=latest_run.get('salidas',{}).get('silver',{})
phase4_path=ROOT/'output/verificacion_fase4.json'
phase4=json.loads(phase4_path.read_text()) if phase4_path.exists() else {}
compute_text='El cómputo utilizado es serverless. La plataforma gestiona Runtime, nodos, workers y finalización. Las versiones reales de Python, Spark y librerías por tarea quedan en pipelines/computo_documentado.json.'
if phase4:
 info=phase4['ejecuciones'][-1]['computo'];silver_libraries=info['silver']['librerias_instaladas'];gold_libraries=info['gold']['librerias_instaladas']
 compute_text=f"Cómputo serverless: Python {info['gold']['python']}, Spark {info['gold']['spark']}. Plata: RapidOCR {silver_libraries.get('rapidocr-onnxruntime','ver registro')}, OpenCV {silver_libraries.get('opencv-python','ver registro')}. Oro: scikit-learn {gold_libraries.get('scikit-learn','ver registro')}, MLflow {gold_libraries.get('mlflow',gold_libraries.get('mlflow-skinny','ver registro'))}. La plataforma gestiona Runtime, nodos, workers y finalización. El detalle completo queda en pipelines/computo_documentado.json."
remote_status=f"Se conservan {len(successful)} ejecuciones integrales exitosas del proyecto en output/ejecuciones."
if len(successful)>=2:remote_status+=' Incluyen el alcance inicial de 31 fotos y la ampliación al origen completo.'
else:remote_status+=' Falta completar y conservar dos ejecuciones exitosas con alcances de fotos distintos.'
droplet_path=ROOT/'output/resultado_droplet.json'
droplet_status='La API ya está instalada en el Droplet, en 127.0.0.1:8000, con reinicio automático. Swagger responde 200; los datos responden 503 porque el usuario AWS cc3105-equipo5 carece de s3:GetObject sobre la publicación Oro.'
if droplet_path.exists():
 droplet=json.loads(droplet_path.read_text())
 if droplet.get('health',{}).get('status')=='ok':droplet_status='La API está desplegada en el Droplet, con lectura real de Oro y acceso exclusivo por loopback. Su salud se comprobó mediante SSH.'
public_path=ROOT/'output/verificacion_api_publica.json'
if public_path.exists():
 public=json.loads(public_path.read_text())
 if public.get('endpoints',{}).get('/health',{}).get('http')==200:
  droplet_status='La API está publicada en http://165.22.137.8:8000/, con lectura real de Oro en S3. Su salud se comprobó desde fuera del Droplet. El contenedor del puerto 8003 se conservó intacto.'


def paragraph(text,style='BodyES'):return Paragraph(text,styles[style])
def footer(c,doc):
 c.setFont('Helvetica',8);c.setFillColor(GRAY);c.drawString(42,25,'Equipo 5 · CC3105 · Corte '+cutoff);c.drawRightString(doc.pagesize[0]-42,25,str(doc.page))
def table(rows,widths=None):
 t=Table(rows,colWidths=widths,hAlign='LEFT');t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),NAVY),('TEXTCOLOR',(0,0),(-1,0),white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),9),('LEADING',(0,0),(-1,-1),12),('ROWBACKGROUNDS',(0,1),(-1,-1),[white,LIGHT]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]));return t

def report():
 # El informe final se entrega compilado; conservar su diseño e imagen elegidos.
 from pypdf import PdfReader
 path=ROOT/'docs/informe.pdf'
 if not path.is_file():raise FileNotFoundError('Falta el informe PDF final en docs/informe.pdf')
 if len(PdfReader(path).pages)>5:raise ValueError('El informe supera el máximo de cinco páginas')
 print('Se conserva el informe PDF final; no se regenera.')

def deck():
 # Conservar la presentación editorial y su versión editable revisadas.
 from pypdf import PdfReader
 pdf=ROOT/'presentacion/presentacion_jurado.pdf'
 pptx=ROOT/'presentacion/presentacion_jurado.pptx'
 if not pdf.is_file():raise FileNotFoundError('Falta la presentación PDF final del equipo')
 if len(PdfReader(pdf).pages)!=10:raise ValueError('La presentación final debe conservar sus diez diapositivas')
 print('Se conserva la presentación final del equipo; no se regenera.')

def summary():
 from build_jury_summary import build
 build()


def review_image(image,max_size):
 image=image.copy();image.thumbnail(max_size)
 buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=93,optimize=True);buffer.seek(0)
 return ImageReader(buffer)

def review_book():
 from pypdf import PdfReader
 existing=ROOT/'output/pdf/cuaderno_revision_20_fotos.pdf'
 if existing.exists():
  fields=PdfReader(existing).get_fields() or {}
  if any(str(v.get('/V','')).strip() not in ('','/Off') for v in fields.values()):
   print('Se conserva el cuaderno con lecturas del usuario');return
 with (ROOT/'data/evaluacion_ocr_manual.csv').open(newline='') as stream:sample=list(csv.DictReader(stream))
 c=canvas.Canvas(str(ROOT/'output/pdf/cuaderno_revision_20_fotos.pdf'),pagesize=(842,595));c.setTitle('Revisión humana de 20 fotografías');c.setAuthor('Equipo 5')
 for i,row in enumerate(sample):
  filename=row['foto_origen'].split('/img/',1)[1];path=ROOT/'data/images'/filename
  with Image.open(path) as img:picture=ImageOps.exif_transpose(img).convert('RGB')
  crop=picture.crop((0,int(picture.height*.5),picture.width,picture.height))
  c.setFillColor(NAVY);c.setFont('Helvetica-Bold',17);c.drawString(24,565,f'{i+1:02d}. {filename}')
  c.setFont('Helvetica',9);c.drawString(24,549,'Leer directamente la imagen. Dejar ilegible en blanco y explicar el motivo. No completar por diferencias entre combustibles.')
  c.drawImage(review_image(picture,(2200,3000)),24,68,width=310,height=462,preserveAspectRatio=True,anchor='c')
  c.drawImage(review_image(crop,(3000,2200)),350,326,width=465,height=203,preserveAspectRatio=True,anchor='c')
  prefix=f'p{i:02d}_'
  def field(label,name,x,y,width=145):
   c.setFillColor(NAVY);c.setFont('Helvetica',9);c.drawString(x,y+22,label)
   c.acroForm.textfield(name=prefix+name,x=x,y=y,width=width,height=18,fontSize=10,borderWidth=.6,borderColor=GRAY,fillColor=white,textColor=NAVY,forceBorder=True)
  field('Diésel Q/galón','diesel',350,286,140);field('Regular Q/galón','regular',510,286,140);field('Súper Q/galón','super',670,286,140)
  field('Ubicación visible','ubicacion',350,240,220);field('Modalidad visible','modalidad',590,240,220)
  field('Nombre del revisor','revisor',350,194,220);field('Confirmar nombre exacto del archivo','archivo',590,194,220)
  field('Observaciones / precios ilegibles','observaciones',350,143,460)
  c.acroForm.checkbox(name=prefix+'confirmado',x=350,y=105,size=14,checked=False,buttonStyle='check',borderColor=GRAY,fillColor=white,textColor=NAVY)
  c.setFont('Helvetica',10);c.drawString(372,108,'Confirmo que revisé esta foto y que estos son los valores visibles.')
  c.setFont('Helvetica',8);c.drawString(350,78,'Guardar una copia del PDF antes de importar las lecturas. No marcar si persiste la duda.')
  c.setFillColor(GRAY);c.drawString(24,24,'Documento de revisión local. Contiene imágenes del curso y queda fuera de Git.');c.showPage()
 c.save()

if __name__=='__main__':
 if '--report-only' in sys.argv:
  report();sys.exit(0)
 if '--review-only' in sys.argv:
  review_book();print('Cuaderno JPEG optimizado generado');sys.exit(0)
 if '--docs-only' in sys.argv:
  report();deck();summary();print('Entregables sin imágenes de revisión actualizados');sys.exit(0)
 report();deck();summary();review_book()
 from pypdf import PdfReader
 for p,n in [(ROOT/'docs/informe.pdf',5),(ROOT/'presentacion/presentacion_jurado.pdf',10),(ROOT/'presentacion/resumen_jurado.pdf',1),(ROOT/'output/pdf/cuaderno_revision_20_fotos.pdf',20)]:
  reader=PdfReader(p);print(p.relative_to(ROOT),len(reader.pages),'páginas')
  if len(reader.pages)!=n:raise ValueError('Número de páginas inesperado')
  if n==20:
   fields=reader.get_fields() or {};assert len(fields)==180,(len(fields),180)
