# Evidencias de orquestación

Capturas originales guardadas por el equipo el 24 de noviembre de 2026. Corresponden al Job operativo `equipo-03-pipeline`, ID `164482682079093`, del proyecto del equipo 5.

| Archivo | Evidencia |
| --- | --- |
| [historial_job.png](historial_job.png) | Historial, las tres tareas encadenadas y programación semanal. |
| [ejecucion_128298002079637.png](ejecucion_128298002079637.png) | Primera ejecución: tres tareas exitosas y sus duraciones. Foto de la semana 2026-01-27. |
| [ejecucion_592769852166445.png](ejecucion_592769852166445.png) | Segunda ejecución: tres tareas exitosas y sus duraciones. Foto de la semana 2026-07-07. |

Ambas ejecuciones releyeron una fotografía existente de semanas distintas y conservaron 110 filas en Bronce. La fecha/semana de cada foto se contrastó con EXIF y el hash del binario de Bronce. Las capturas muestran los identificadores que permiten relacionarlas con esa verificación.

[manifest.json](manifest.json) registra SHA256 de cada captura, ejecución, foto, semana y duraciones. Los valores de duración visibles en la UI y `execution_duration` obtenidos por API son métricas distintas y se conservan por separado.
