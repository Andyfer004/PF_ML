"""Genera el resumen académico de una página; conserva únicamente el PDF final."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
CONTENT = r'''\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[provide=*,spanish]{babel}
\usepackage{geometry,hyperref,microtype,mathpazo,booktabs}
\geometry{margin=2.5cm}
\hypersetup{colorlinks=true,urlcolor=blue,pdftitle={Resumen para el jurado: precio de la gasolina en Guatemala},pdfauthor={Equipo 5}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\makeatletter
\renewcommand\section{\@startsection{section}{1}{0pt}{9pt}{4pt}{\large\bfseries}}
\makeatother
\emergencystretch=2em
\begin{document}
\begin{center}
{\large\textbf{Universidad del Valle de Guatemala}}\\[2pt]
Facultad de Ingeniería \enspace $\cdot$ \enspace CC3105\\[7pt]
{\Large\textbf{Predicción del precio de la gasolina\\en Guatemala}}\\[5pt]
\textbf{Resumen para el jurado -- Equipo 5}\\[2pt]
25 de noviembre de 2026
\end{center}
\vspace{2pt}\hrule\vspace{6pt}

\section*{Problema y objetivo}
El proyecto clasifica si el precio de súper, regular y diésel sube, baja o se
mantiene la semana siguiente, para apoyar la planificación de compras de
combustible. Utiliza 110 fotografías y 11,427 observaciones únicas del histórico
oficial del MEM. Expresa los precios en quetzales por galón y agrupa semanas de
martes a lunes.

\section*{Arquitectura y extracción}
Amazon S3 almacena tres capas: Bronce conserva fotografías y metadatos; Plata
extrae texto con RapidOCR y OpenCV, aplica controles y separa rechazos; Oro genera
indicadores y predicciones. Un Job de Databricks encadena las tareas y publica
Parquet para FastAPI en DigitalOcean. La interfaz web consume esa API.

La revisión manual de 20 fotos identificó 33 precios legibles. El OCR extrajo 18
y acertó 17: \textbf{94.4\,\% de precisión}, 54.5\,\% de cobertura y 51.5\,\% de
exactitud incluyendo omisiones. El lote completo contiene 126 registros
aceptados y 278 rechazados. Las lecturas dudosas se excluyen del entrenamiento.

\section*{Modelo y resultados}
Un árbol de decisión predice la dirección con horizonte de una semana mediante
precios y cambios anteriores. Se evalúa con separación temporal y se compara
contra repetir la última dirección conocida, sobre 417 casos MEM.

\begin{center}
\begin{tabular}{lrr}
\toprule
\textbf{Medida} & \textbf{Modelo} & \textbf{Línea base}\\
\midrule
Exactitud & 58.75\,\% & 57.07\,\%\\
Macro F1 & 0.542 & 0.558\\
\bottomrule
\end{tabular}
\end{center}
El modelo mejora la exactitud en 1.68 puntos porcentuales, pero no supera la
línea base en macro F1. La demostración es histórica: muestra la semana del
10 de noviembre de 2026 y declara su corte simulado; no representa un
pronóstico vigente.

\section*{Demostración pública}
\textbf{Interfaz web:} \url{http://165.22.137.8:8000/}\\
\textbf{API y consultas interactivas:} \url{http://165.22.137.8:8000/docs}

La demo permite consultar precios, histórico, predicciones por combustible y
métricas. Actualizar las fuentes y ampliar la muestra legible son los siguientes
pasos para evaluar pronósticos vigentes.
\end{document}
'''


def build():
    compiler = shutil.which('tectonic')
    if not compiler:
        raise RuntimeError('Se requiere Tectonic para generar el resumen.')
    with tempfile.TemporaryDirectory(prefix='resumen-jurado-') as directory:
        source = Path(directory) / 'resumen.tex'
        source.write_text(CONTENT)
        subprocess.run([compiler, str(source), '--outdir', directory], check=True)
        result = Path(directory) / 'resumen.pdf'
        if len(PdfReader(result).pages) != 1:
            raise ValueError('El resumen debe ocupar una página; revisar maquetación.')
        shutil.copyfile(result, ROOT / 'presentacion/resumen_jurado.pdf')
    print('Resumen para el jurado actualizado: una página.')


if __name__ == '__main__':
    build()
