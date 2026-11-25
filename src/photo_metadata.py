"""Metadatos visibles: abstención ante ausencia, baja confianza o ambigüedad."""
import re
import unicodedata


def extract_metadata(lines):
    candidates = {'ubicacion': {}, 'modalidad': {}}
    for line in lines:
        text = ' '.join(str(line.get('texto', '')).split())
        if float(line.get('confianza', 0)) < .90:
            continue
        folded = ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                         if not unicodedata.combining(c))
        modes = []
        if re.search(r'\b(auto\s*servicio|self[ -]?service)\b', folded):
            modes.append('autoservicio')
        if re.search(r'\b(servicio\s+completo|full[ -]?service)\b', folded):
            modes.append('servicio completo')
        for mode in modes:
            candidates['modalidad'].setdefault(mode, text)
        # Se exige un campo explícito y su valor en la misma línea. Una marca,
        # un precio o un nombre de archivo no identifican una estación.
        match = re.fullmatch(r'(?:ubicaci[oó]n|direcci[oó]n|municipio|departamento|estaci[oó]n)\s*:\s*(.{3,100})', text, re.I)
        if match:
            value = match.group(1).strip(' .;,')
            if re.search(r'[a-záéíóúñ]{3}', value, re.I) and not re.search(
                    r'\b(no visible|no identificad[ao]|desconocid[ao]|n/?a)\b', value, re.I):
                candidates['ubicacion'].setdefault(value.casefold(), text)
    result = {'ubicacion': 'no_identificada', 'modalidad': 'no_identificada',
              'evidencia_metadatos': {}, 'version_metadatos': 'visibles-v1'}
    for field, values in candidates.items():
        if len(values) == 1:
            key, evidence = next(iter(values.items()))
            result[field] = key if field == 'modalidad' else evidence.split(':', 1)[1].strip(' .;,')
            result['evidencia_metadatos'][field] = evidence
    return result
