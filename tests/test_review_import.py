import csv,unittest
from pathlib import Path
from unittest.mock import patch
from scripts.import_review_pdf import extract,ROOT
class ReviewImportTests(unittest.TestCase):
    def fields(self,confirm='/Yes',price='36.19'):
        with (ROOT/'data/evaluacion_ocr_manual.csv').open(newline='') as stream:row=next(csv.DictReader(stream))
        data={'confirmado':confirm,'revisor':'revisor_de_prueba','archivo':Path(row['foto_origen']).name,'super':price,'observaciones':'Otros precios ilegibles en esta prueba'}
        return {'p00_'+k:{'/V':v} for k,v in data.items()}
    def test_blank_or_unconfirmed_form_is_not_a_human_reference(self):
        with patch('scripts.import_review_pdf.PdfReader') as reader:
            reader.return_value.get_fields.return_value=self.fields('/Off')
            self.assertEqual(extract('unused.pdf'),[])
    def test_confirmation_requires_reviewer_filename_and_valid_prices(self):
        with patch('scripts.import_review_pdf.PdfReader') as reader:
            reader.return_value.get_fields.return_value=self.fields()
            result=extract('unused.pdf');self.assertEqual(len(result),1)
            self.assertEqual(result[0]['confirmado_equipo'],'true')
            reader.return_value.get_fields.return_value=self.fields(price='NaN')
            with self.assertRaises(ValueError):extract('unused.pdf')
    def test_confirmed_relative_folder_matches_the_exact_source_photo(self):
        with (ROOT/'data/evaluacion_ocr_manual.csv').open(newline='') as stream:row=next(csv.DictReader(stream))
        fields=self.fields();fields['p00_archivo']['/V']=row['foto_origen'].split('/img/',1)[-1]
        with patch('scripts.import_review_pdf.PdfReader') as reader:
            reader.return_value.get_fields.return_value=fields
            self.assertEqual(len(extract('unused.pdf')),1)
